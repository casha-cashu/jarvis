use serde::{Deserialize, Serialize};
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tauri::Emitter;

struct BridgeProcess {
  child: Child,
  stdin: ChildStdin,
  responses: Receiver<String>,
}

struct AppState {
  bridge: Mutex<Option<BridgeProcess>>,
  started: AtomicBool,
}

#[derive(Serialize)]
struct BackendStatus {
  running: bool,
  connected: bool,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct ApiPresetConfig {
  r#type: String,
  endpoint: String,
  api_key: String,
  model: String,
  #[serde(default = "default_true")]
  agent_enabled: bool,
  #[serde(default)]
  approval_mode: String,
}

fn default_true() -> bool {
  true
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct MicrophoneDevice { name: String, description: String, is_default: bool }

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SystemStats { uptime_seconds: u64, memory_used_mb: u64, memory_total_mb: u64, load_average: f64, platform: String }

fn bridge_root() -> PathBuf {
  // Repo root = two levels above src-tauri (jarvis-ui/src-tauri).
  std::env::var_os("JARVIS_PYTHON_ROOT")
    .map(PathBuf::from)
    .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../.."))
}

fn ensure_bridge(state: &AppState) -> Result<(), String> {
  let mut guard = state.bridge.lock().map_err(|_| "Состояние bridge повреждено")?;
  if guard.is_some() {
    return Ok(());
  }
  let root = bridge_root();
  let script = root.join("jarvis").join("ui_bridge.py");
  let python = std::env::var_os("JARVIS_PYTHON")
    .map(PathBuf::from)
    .unwrap_or_else(|| root.join("venv/bin/python"));
  let mut child = Command::new(python)
    .arg("-u")
    .arg(&script)
    .current_dir(&root)
    .env("PYTHONPATH", &root)
    .stdin(Stdio::piped())
    .stdout(Stdio::piped())
    .stderr(Stdio::inherit())
    .spawn()
    .map_err(|e| format!("Не удалось запустить Python bridge: {e}"))?;
  let stdin = child.stdin.take().ok_or("Не удалось открыть stdin bridge")?;
  let stdout = child.stdout.take().ok_or("Не удалось открыть stdout bridge")?;
  let (tx, rx) = mpsc::channel();
  std::thread::spawn(move || {
    for line in BufReader::new(stdout).lines().flatten() {
      let _ = tx.send(line);
    }
  });
  *guard = Some(BridgeProcess { child, stdin, responses: rx });
  state.started.store(true, Ordering::SeqCst);
  Ok(())
}

/// Kills a dead/stuck bridge so the next request spawns a fresh one.
fn shutdown_bridge(state: &AppState) {
  state.started.store(false, Ordering::SeqCst);
  if let Ok(mut guard) = state.bridge.lock() {
    if let Some(mut bridge) = guard.take() {
      let _ = bridge.child.kill();
      let _ = bridge.child.wait();
    }
  }
}

fn request(state: &AppState, payload: &str) -> Result<serde_json::Value, String> {
  match request_inner(state, payload) {
    Ok(v) => Ok(v),
    // Dead or stuck python process: clean up so the NEXT call respawns it
    // instead of timing out forever against a corpse.
    Err(e) => {
      shutdown_bridge(state);
      Err(e)
    }
  }
}

fn request_inner(state: &AppState, payload: &str) -> Result<serde_json::Value, String> {
  ensure_bridge(state)?;
  let mut guard = state.bridge.lock().map_err(|_| "Состояние bridge повреждено")?;
  let bridge = guard.as_mut().ok_or("Bridge не запущен")?;
  writeln!(bridge.stdin, "{payload}").map_err(|e| format!("Ошибка IPC: {e}"))?;
  bridge.stdin.flush().map_err(|e| format!("Ошибка IPC: {e}"))?;
  let response = bridge.responses.recv_timeout(Duration::from_secs(60))
    .map_err(|e| format!("Python не ответил: {e}"))?;
  serde_json::from_str(&response).map_err(|e| format!("Некорректный ответ Python: {e}"))
}

#[tauri::command]
async fn backend_start(state: tauri::State<'_, Arc<AppState>>) -> Result<serde_json::Value, String> {
  run_bridge(state, r#"{"command":"start"}"#.to_string()).await
}

#[tauri::command]
fn backend_stop(state: tauri::State<'_, Arc<AppState>>) -> Result<String, String> {
  let mut guard = state.bridge.lock().map_err(|_| "Состояние bridge повреждено")?;
  state.started.store(false, Ordering::SeqCst);
  if let Some(mut bridge) = guard.take() {
    let _ = writeln!(bridge.stdin, "{{\"command\":\"stop\"}}");
    let _ = bridge.child.kill();
  }
  Ok(r#"{"ok":true}"#.to_string())
}

#[tauri::command]
fn backend_status(state: tauri::State<'_, Arc<AppState>>) -> BackendStatus {
  let connected = state.started.load(Ordering::SeqCst);
  BackendStatus { running: connected, connected }
}

/// Like request(), but streams intermediate {"stream":true,"delta":...}
/// lines as Tauri events and returns the final response object.
fn stream_request(app: &tauri::AppHandle, state: &AppState, payload: &str) -> Result<serde_json::Value, String> {
  match stream_request_inner(app, state, payload) {
    Ok(v) => Ok(v),
    Err(e) => {
      shutdown_bridge(state);
      Err(e)
    }
  }
}

fn stream_request_inner(app: &tauri::AppHandle, state: &AppState, payload: &str) -> Result<serde_json::Value, String> {
  ensure_bridge(state)?;
  let mut guard = state.bridge.lock().map_err(|_| "Состояние bridge повреждено")?;
  let bridge = guard.as_mut().ok_or("Bridge не запущен")?;
  writeln!(bridge.stdin, "{payload}").map_err(|e| format!("Ошибка IPC: {e}"))?;
  bridge.stdin.flush().map_err(|e| format!("Ошибка IPC: {e}"))?;
  loop {
    let line = bridge.responses.recv_timeout(Duration::from_secs(180))
      .map_err(|e| format!("Python не ответил: {e}"))?;
    let value: serde_json::Value = serde_json::from_str(&line)
      .map_err(|e| format!("Некорректный ответ Python: {e}"))?;
    if value.get("stream").and_then(|s| s.as_bool()).unwrap_or(false) {
      if let Some(delta) = value.get("delta").and_then(|d| d.as_str()) {
        let _ = app.emit("chat-stream", delta);
      }
      continue;
    }
    if let Some(tool) = value.get("tool") {
      let _ = app.emit("chat-tool", tool.to_string());
      continue;
    }
    if let Some(result) = value.get("tool_result") {
      let _ = app.emit("chat-tool-result", result.to_string());
      continue;
    }
    return Ok(value);
  }
}

#[tauri::command]
async fn backend_send_message(message: String, session: Option<String>, app: tauri::AppHandle, state: tauri::State<'_, Arc<AppState>>) -> Result<serde_json::Value, String> {
  let payload = serde_json::json!({"command": "message", "text": message, "session": session}).to_string();
  let app = app.clone();
  let state: Arc<AppState> = state.inner().clone();
  tauri::async_runtime::spawn_blocking(move || stream_request(&app, &state, &payload))
    .await
    .map_err(|e| format!("Внутренняя ошибка: {e}"))?
}

#[tauri::command]
async fn backend_configure(config: ApiPresetConfig, state: tauri::State<'_, Arc<AppState>>) -> Result<serde_json::Value, String> {
  let payload = serde_json::json!({"command": "configure", "config": {"type": config.r#type, "endpoint": config.endpoint, "api_key": config.api_key, "model": config.model, "agent_enabled": config.agent_enabled, "approval_mode": config.approval_mode}}).to_string();
  run_bridge(state, payload).await
}

#[tauri::command]
async fn backend_list_models(config: ApiPresetConfig, state: tauri::State<'_, Arc<AppState>>) -> Result<serde_json::Value, String> {
  let payload = serde_json::json!({"command": "list_models", "config": {"type": config.r#type, "endpoint": config.endpoint, "api_key": config.api_key, "model": config.model}}).to_string();
  run_bridge(state, payload).await
}

#[tauri::command]
async fn backend_timers(state: tauri::State<'_, Arc<AppState>>) -> Result<serde_json::Value, String> {
  run_bridge(state, r#"{"command":"timers"}"#.to_string()).await
}

#[tauri::command]
async fn backend_clear_history(state: tauri::State<'_, Arc<AppState>>) -> Result<serde_json::Value, String> {
  run_bridge(state, r#"{"command":"clear_history"}"#.to_string()).await
}

#[tauri::command]
async fn backend_switch_session(id: String, state: tauri::State<'_, Arc<AppState>>) -> Result<serde_json::Value, String> {
  let payload = serde_json::json!({"command": "switch_session", "id": id}).to_string();
  run_bridge(state, payload).await
}

#[tauri::command]
async fn backend_delete_session(id: String, state: tauri::State<'_, Arc<AppState>>) -> Result<serde_json::Value, String> {
  let payload = serde_json::json!({"command": "delete_session", "id": id}).to_string();
  run_bridge(state, payload).await
}

/// Runs a blocking bridge request off the async runtime so the UI never freezes.
async fn run_bridge(
  state: tauri::State<'_, Arc<AppState>>,
  payload: String,
) -> Result<serde_json::Value, String> {
  let app: Arc<AppState> = state.inner().clone();
  tauri::async_runtime::spawn_blocking(move || request(&app, &payload))
    .await
    .map_err(|e| format!("Внутренняя ошибка: {e}"))?
}

#[tauri::command]
fn list_microphones() -> Result<Vec<MicrophoneDevice>, String> {
  let output = Command::new("pactl").args(["list", "sources"]).output().map_err(|e| format!("pactl недоступен: {e}"))?;
  let text = String::from_utf8_lossy(&output.stdout);
  let default = Command::new("pactl").args(["get-default-source"]).output().ok().map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string()).unwrap_or_default();
  let mut devices = Vec::new();
  let mut pending_name: Option<String> = None;
  for line in text.lines() {
    let trimmed = line.trim();
    if let Some(value) = trimmed.strip_prefix("Name: ") { pending_name = Some(value.to_string()); }
    if let (Some(name), Some(description)) = (&pending_name, trimmed.strip_prefix("Description: ")) {
      if !name.contains(".monitor") { devices.push(MicrophoneDevice { is_default: name == &default, name: name.clone(), description: description.to_string() }); }
    }
  }
  Ok(devices)
}

#[tauri::command]
fn set_default_microphone(name: String) -> Result<(), String> {
  let status = Command::new("pactl").args(["set-default-source", &name]).status().map_err(|e| format!("pactl недоступен: {e}"))?;
  if status.success() { Ok(()) } else { Err("Не удалось выбрать микрофон".into()) }
}

#[tauri::command]
fn system_stats() -> Result<SystemStats, String> {
  let uptime = std::fs::read_to_string("/proc/uptime").unwrap_or_default().split_whitespace().next().and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0) as u64;
  let mem = std::fs::read_to_string("/proc/meminfo").unwrap_or_default();
  let value = |key: &str| mem.lines().find(|line| line.starts_with(key)).and_then(|line| line.split_whitespace().nth(1)).and_then(|v| v.parse::<u64>().ok()).unwrap_or(0) / 1024;
  let total = value("MemTotal:");
  let available = value("MemAvailable:");
  let load = std::fs::read_to_string("/proc/loadavg").unwrap_or_default().split_whitespace().next().and_then(|v| v.parse::<f64>().ok()).unwrap_or(0.0);
  Ok(SystemStats { uptime_seconds: uptime, memory_used_mb: total.saturating_sub(available), memory_total_mb: total, load_average: load, platform: std::env::consts::OS.to_string() })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .manage(Arc::new(AppState { bridge: Mutex::new(None), started: AtomicBool::new(false) }))
    .invoke_handler(tauri::generate_handler![backend_start, backend_stop, backend_status, backend_send_message, backend_configure, backend_list_models, backend_timers, backend_clear_history, backend_switch_session, backend_delete_session, list_microphones, set_default_microphone, system_stats])
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }
      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
