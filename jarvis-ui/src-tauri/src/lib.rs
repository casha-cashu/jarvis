use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicU64, Ordering};
use std::sync::mpsc::{self, SyncSender};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tauri::{Emitter, Manager};

struct BridgeProcess {
  child: Child,
}

struct AppState {
  bridge: Mutex<Option<BridgeProcess>>,
  /// Отдельно от bridge: backend_stop закрывает stdin, НЕ дожидаясь
  /// мьютекса, который держит 180-секундный стриминг (иначе «Стоп»
  /// срабатывал только после конца генерации).
  stdin: Mutex<Option<ChildStdin>>,
  child_pid: AtomicU32,
  started: AtomicBool,
  /// Мультиплексирование: id запроса -> канал его финального ответа.
  /// Reader-поток доставляет строки адресно; стрим/инструменты уходят
  /// в события мимо каналов. Arc — reader держит клон после spawn'а.
  pending: Arc<Mutex<HashMap<String, SyncSender<String>>>>,
  /// Поколение bridge: reader при EOF чистит pending только если
  /// поколение не сменилось (иначе затирает pending нового моста).
  bridge_epoch: Arc<AtomicU64>,
  app: Arc<Mutex<Option<tauri::AppHandle>>>,
  req_counter: AtomicU64,
  /// Packaged builds only: user config seeded from bundled resources,
  /// forwarded to the sidecar as JARVIS_CONFIG_PATH.
  packaged_config: Mutex<Option<PathBuf>>,
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

/// Sidecar backend shipped next to the main executable in release bundles
/// (Tauri externalBin: binaries/jarvis-bridge[-<target triple>]).
fn sidecar_path() -> Option<PathBuf> {
  if cfg!(debug_assertions) {
    return None;
  }
  let dir = std::env::current_exe().ok()?.parent()?.to_path_buf();
  std::fs::read_dir(&dir)
    .ok()?
    .filter_map(Result::ok)
    .map(|entry| entry.path())
    .find(|path| {
      path.is_file()
        && path
          .file_name()
          .and_then(|name| name.to_str())
          .is_some_and(|name| {
            // Точный матч: сторонний файл вида jarvis-bridge.txt не должен
            // стать целью спавна.
            name == "jarvis-bridge" || name.starts_with("jarvis-bridge-")
          })
    })
}

/// Prepares the bridge command for the current runtime mode: the bundled
/// PyInstaller sidecar in packaged builds, venv-python + ui_bridge.py in dev.
fn bridge_command(state: &AppState) -> Command {
  match sidecar_path() {
    Some(bin) => {
      let mut command = Command::new(bin);
      if let Ok(slot) = state.packaged_config.lock() {
        if let Some(config) = slot.as_ref() {
          command.env("JARVIS_CONFIG_PATH", config);
        }
      }
      command
    }
    None => {
      // Dev fallback: run ui_bridge.py from the repo via the shared venv.
      // In release this means sidecar was not found — hint in error below.
      let root = bridge_root();
      let script = root.join("jarvis").join("ui_bridge.py");
      let python = std::env::var_os("JARVIS_PYTHON")
        .map(PathBuf::from)
        .unwrap_or_else(|| root.join("venv/bin/python"));
      if cfg!(not(debug_assertions)) && !python.is_file() {
        log::warn!("sidecar not found next to current_exe and venv python missing at {} — packaged build may be corrupted", python.display());
      }
      let mut command = Command::new(python);
      command
        .arg("-u")
        .arg(&script)
        .current_dir(&root)
        .env("PYTHONPATH", &root);
      command
    }
  }
}

fn ensure_bridge(state: &AppState) -> Result<(), String> {
  let mut guard = state.bridge.lock().map_err(|_| "Состояние bridge повреждено")?;
  if guard.is_some() {
    return Ok(());
  }
  let mut command = bridge_command(state);
  command
    .stdin(Stdio::piped())
    .stdout(Stdio::piped())
    .stderr(Stdio::inherit());
  let mut child = command
    .spawn()
    .map_err(|e| format!("Не удалось запустить Python bridge: {e}"))?;
  let stdin = child.stdin.take().ok_or("Не удалось открыть stdin bridge")?;
  let stdout = child.stdout.take().ok_or("Не удалось открыть stdout bridge")?;
  state.child_pid.store(child.id(), Ordering::SeqCst);
  if let Ok(mut stdin_slot) = state.stdin.lock() {
    *stdin_slot = Some(stdin);
  }
  *guard = Some(BridgeProcess { child });

  // Reader: адресует финальные ответы по id, стрим/инструменты — в события.
  let pending = Arc::clone(&state.pending);
  let app_slot = Arc::clone(&state.app);
  let epoch_slot = Arc::clone(&state.bridge_epoch);
  let epoch = epoch_slot.load(Ordering::SeqCst);
  std::thread::spawn(move || {
    for line in BufReader::new(stdout).lines().flatten() {
      let value: serde_json::Value = match serde_json::from_str(&line) {
        Ok(v) => v,
        Err(_) => continue, // мусорный вывод python не рвёт протокол
      };
      // Сперва адресация: стрим/инструменты помечены id активного
      // message и уходят в персональный канал (stream_request сам эмитит
      // события и сбрасывает таймаут на каждую строку).
      if let Some(id) = value.get("id").and_then(|v| v.as_str()).map(String::from) {
        let delivered = pending
          .lock()
          .ok()
          .and_then(|mut p| p.remove(&id))
          .is_some_and(|tx| tx.send(line).is_ok());
        if delivered {
          continue;
        }
        // Канала нет (таймаут/закрытие) — строка больше никому не нужна.
        continue;
      }
      // Легаси: строки без id — только события.
      if value.get("stream").is_some() || value.get("tool").is_some() {
        if let Ok(slot) = app_slot.lock() {
          if let Some(app) = slot.as_ref() {
            if value.get("stream").is_some() {
              if let Some(delta) = value.get("delta").and_then(|d| d.as_str()) {
                let _ = app.emit("chat-stream", delta);
              }
            } else if let Some(tool) = value.get("tool") {
              let _ = app.emit("chat-tool", tool.to_string());
            } else if let Some(result) = value.get("tool_result") {
              let _ = app.emit("chat-tool-result", result.to_string());
            }
          }
        }
      }
    }
    // EOF/python умер: будим ждущих ТОЛЬКО своего поколения — старый
    // reader, проснувшись после пересоздания моста, не должен стирать
    // pending нового (гонка найдена adversarial-ревью).
    if epoch_slot.load(Ordering::SeqCst) == epoch {
      if let Ok(mut pending) = pending.lock() {
        pending.clear();
      }
    }
  });

  state.started.store(true, Ordering::SeqCst);
  Ok(())
}

/// Kills a dead/stuck bridge so the next request spawns a fresh one.
fn shutdown_bridge(state: &AppState) {
  state.started.store(false, Ordering::SeqCst);
  state.child_pid.store(0, Ordering::SeqCst);
  state.bridge_epoch.fetch_add(1, Ordering::SeqCst);
  if let Ok(mut pending) = state.pending.lock() {
    pending.clear(); // закрывает каналы — ждущие запросы получают ошибку
  }
  if let Ok(mut stdin_slot) = state.stdin.lock() {
    *stdin_slot = None; // EOF на случай ещё живого python
  }
  if let Ok(mut guard) = state.bridge.lock() {
    if let Some(mut bridge) = guard.take() {
      let _ = bridge.child.kill();
      let _ = bridge.child.wait();
    }
  }
}

fn request(state: &AppState, payload: serde_json::Value, timeout: Duration) -> Result<serde_json::Value, String> {
  match request_inner(state, payload, timeout) {
    Ok(v) => Ok(v),
    // Dead or stuck python process: clean up so the NEXT call respawns it
    // instead of timing out forever against a corpse.
    Err(e) => {
      shutdown_bridge(state);
      Err(e)
    }
  }
}

/// Мультиплексированный запрос: id в payload, ответ доставляется reader'ом
/// в персональный канал — глобальный мьютекс на время ожидания НЕ держится.
fn request_inner(state: &AppState, mut payload: serde_json::Value, timeout: Duration) -> Result<serde_json::Value, String> {
  ensure_bridge(state)?;
  let id = format!("r{}", state.req_counter.fetch_add(1, Ordering::SeqCst));
  let (tx, rx) = mpsc::sync_channel::<String>(1);
  state
    .pending
    .lock()
    .map_err(|_| "Состояние bridge повреждено")?
    .insert(id.clone(), tx);
  payload["id"] = serde_json::json!(id);
  if let Err(e) = write_request(state, payload.to_string().as_str()) {
    if let Ok(mut pending) = state.pending.lock() {
      pending.remove(&id);
    }
    return Err(e);
  }
  let line = match rx.recv_timeout(timeout) {
    Ok(line) => line,
    Err(e) => {
      if let Ok(mut pending) = state.pending.lock() {
        pending.remove(&id);
      }
      return Err(format!("Python не ответил: {e}"));
    }
  };
  serde_json::from_str(&line).map_err(|e| format!("Некорректный ответ Python: {e}"))
}

/// Пишет строку запроса в stdin моста. Отдельная функция + отдельный
/// мьютекс: backend_stop не должен ждать request-канал, чтобы закрыть stdin.
fn write_request(state: &AppState, payload: &str) -> Result<(), String> {
  let mut stdin_guard = state.stdin.lock().map_err(|_| "Состояние bridge повреждено")?;
  let stdin = stdin_guard.as_mut().ok_or("Bridge не запущен")?;
  writeln!(stdin, "{payload}").map_err(|e| format!("Ошибка IPC: {e}"))?;
  stdin.flush().map_err(|e| format!("Ошибка IPC: {e}"))
}

#[tauri::command]
async fn backend_start(state: tauri::State<'_, Arc<AppState>>) -> Result<serde_json::Value, String> {
  run_bridge(state, serde_json::json!({"command":"start"}), Duration::from_secs(60)).await
}

#[tauri::command]
async fn backend_stop(state: tauri::State<'_, Arc<AppState>>) -> Result<String, String> {
  // Async + spawn_blocking: sync-команды Tauri выполняются в main thread.
  // Отмена реальная, а не отложенная: stdin закрывается БЕЗ ожидания
  // занятого канала, затем SIGTERM по pid — раньше «Стоп» во время
  // генерации не делал ничего до её конца.
  let state: Arc<AppState> = state.inner().clone();
  tauri::async_runtime::spawn_blocking(move || {
    state.started.store(false, Ordering::SeqCst);
    let pid = state.child_pid.load(Ordering::SeqCst);
    // EOF на stdin: python завершится после текущего запроса и корректно
    // погасит response pipeline.
    if let Ok(mut stdin_slot) = state.stdin.lock() {
      if let Some(mut stdin) = stdin_slot.take() {
        let _ = writeln!(stdin, "{{\"command\":\"stop\"}}");
      }
    }
    // Разбудить ждущие мультиплексированные запросы.
    if let Ok(mut pending) = state.pending.lock() {
      pending.clear();
    }
    std::thread::sleep(Duration::from_millis(500));
    if pid != 0 {
      let _ = Command::new("kill").args(["-TERM", &pid.to_string()]).status();
    }
    // Reap: kill по уже мёртвому pid безвреден, wait убирает зомби.
    if let Ok(mut guard) = state.bridge.lock() {
      if let Some(mut bridge) = guard.take() {
        let _ = bridge.child.kill();
        let _ = bridge.child.wait();
      }
    }
    state.child_pid.store(0, Ordering::SeqCst);
    Ok(r#"{"ok":true}"#.to_string())
  })
  .await
  .map_err(|e| format!("Внутренняя ошибка: {e}"))?
}

#[tauri::command]
fn backend_status(state: tauri::State<'_, Arc<AppState>>) -> BackendStatus {
  let connected = state.started.load(Ordering::SeqCst);
  BackendStatus { running: connected, connected }
}

/// Стриминговый запрос: дельты/инструменты reader уводит в события,
/// финальная строка приходит в персональный канал.
fn stream_request(app: &tauri::AppHandle, state: &AppState, payload: serde_json::Value) -> Result<serde_json::Value, String> {
  match stream_request_inner(app, state, payload) {
    Ok(v) => Ok(v),
    Err(e) => {
      shutdown_bridge(state);
      Err(e)
    }
  }
}

fn stream_request_inner(app: &tauri::AppHandle, state: &AppState, mut payload: serde_json::Value) -> Result<serde_json::Value, String> {
  ensure_bridge(state)?;
  let id = format!("s{}", state.req_counter.fetch_add(1, Ordering::SeqCst));
  let (tx, rx) = mpsc::sync_channel::<String>(4);
  state
    .pending
    .lock()
    .map_err(|_| "Состояние bridge повреждено")?
    .insert(id.clone(), tx);
  payload["id"] = serde_json::json!(id);
  if let Err(e) = write_request(state, payload.to_string().as_str()) {
    if let Ok(mut pending) = state.pending.lock() {
      pending.remove(&id);
    }
    return Err(e);
  }
  loop {
    let line = match rx.recv_timeout(Duration::from_secs(180)) {
      Ok(line) => line,
      Err(e) => {
        if let Ok(mut pending) = state.pending.lock() {
          pending.remove(&id);
        }
        return Err(format!("Python не ответил: {e}"));
      }
    };
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
  let payload = serde_json::json!({"command": "message", "text": message, "session": session});
  let app = app.clone();
  let state: Arc<AppState> = state.inner().clone();
  tauri::async_runtime::spawn_blocking(move || stream_request(&app, &state, payload))
    .await
    .map_err(|e| format!("Внутренняя ошибка: {e}"))?
}

#[tauri::command]
async fn backend_configure(config: ApiPresetConfig, state: tauri::State<'_, Arc<AppState>>) -> Result<serde_json::Value, String> {
  let payload = serde_json::json!({"command": "configure", "config": {"type": config.r#type, "endpoint": config.endpoint, "api_key": config.api_key, "model": config.model, "agent_enabled": config.agent_enabled, "approval_mode": config.approval_mode}});
  run_bridge(state, payload, Duration::from_secs(60)).await
}

#[tauri::command]
async fn backend_list_models(config: ApiPresetConfig, state: tauri::State<'_, Arc<AppState>>) -> Result<serde_json::Value, String> {
  let payload = serde_json::json!({"command": "list_models", "config": {"type": config.r#type, "endpoint": config.endpoint, "api_key": config.api_key, "model": config.model}});
  run_bridge(state, payload, Duration::from_secs(60)).await
}

#[tauri::command]
async fn backend_timers(state: tauri::State<'_, Arc<AppState>>) -> Result<serde_json::Value, String> {
  run_bridge(state, serde_json::json!({"command":"timers"}), Duration::from_secs(60)).await
}

#[tauri::command]
async fn backend_clear_history(state: tauri::State<'_, Arc<AppState>>) -> Result<serde_json::Value, String> {
  run_bridge(state, serde_json::json!({"command":"clear_history"}), Duration::from_secs(60)).await
}

#[tauri::command]
async fn backend_switch_session(id: String, state: tauri::State<'_, Arc<AppState>>) -> Result<serde_json::Value, String> {
  let payload = serde_json::json!({"command": "switch_session", "session_id": id});
  run_bridge(state, payload, Duration::from_secs(60)).await
}

#[tauri::command]
async fn backend_delete_session(id: String, state: tauri::State<'_, Arc<AppState>>) -> Result<serde_json::Value, String> {
  let payload = serde_json::json!({"command": "delete_session", "session_id": id});
  run_bridge(state, payload, Duration::from_secs(60)).await
}

#[tauri::command]
async fn backend_purge_session(id: String, state: tauri::State<'_, Arc<AppState>>) -> Result<serde_json::Value, String> {
  // purge_session: delete-архива + очистка живого контекста, если чат активен.
  let payload = serde_json::json!({"command": "purge_session", "session_id": id});
  run_bridge(state, payload, Duration::from_secs(60)).await
}

#[tauri::command]
async fn backend_purge_all_sessions(state: tauri::State<'_, Arc<AppState>>) -> Result<serde_json::Value, String> {
  // «Удалить всю память модели»: без purge архивы ui-history/<sid>.json
  // воскресали удалённый контекст при следующем switch_session.
  run_bridge(state, serde_json::json!({"command":"purge_all_sessions"}), Duration::from_secs(60)).await
}

#[tauri::command]
async fn backend_get_config(state: tauri::State<'_, Arc<AppState>>) -> Result<serde_json::Value, String> {
  // Read-only: текущие значения config.yaml для настроек GUI
  run_bridge(state, serde_json::json!({"command":"get_config"}), Duration::from_secs(60)).await
}

/// Runs a blocking bridge request off the async runtime so the UI never freezes.
async fn run_bridge(
  state: tauri::State<'_, Arc<AppState>>,
  payload: serde_json::Value,
  timeout: Duration,
) -> Result<serde_json::Value, String> {
  let app: Arc<AppState> = state.inner().clone();
  tauri::async_runtime::spawn_blocking(move || request(&app, payload, timeout))
    .await
    .map_err(|e| format!("Внутренняя ошибка: {e}"))?
}

#[tauri::command]
async fn list_microphones() -> Result<Vec<MicrophoneDevice>, String> {
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
async fn set_default_microphone(name: String) -> Result<(), String> {
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

/// Packaged builds ship config.example.yaml as a Tauri resource. On first
/// launch copy it to ~/.config/jarvis/config.yaml and point the sidecar at it.
fn seed_user_config(app: &tauri::AppHandle) -> Result<(), String> {
  use tauri::Manager;
  let resource_dir = app
    .path()
    .resource_dir()
    .map_err(|e| format!("Не удалось определить каталог ресурсов: {e}"))?;
  // Tauri preserves relative structure: "../../config.example.yaml" lands as
  // /usr/lib/JARVIS/_up/_up/config.example.yaml — search recursively.
  fn find_example(dir: &std::path::Path) -> Option<PathBuf> {
    let mut stack = vec![dir.to_path_buf()];
    while let Some(cur) = stack.pop() {
      if let Ok(entries) = std::fs::read_dir(&cur) {
        for e in entries.filter_map(Result::ok) {
          let p = e.path();
          if p.is_file() && p.file_name().and_then(|n| n.to_str()) == Some("config.example.yaml") {
            return Some(p);
          }
          if p.is_dir() {
            stack.push(p);
          }
        }
      }
    }
    None
  }
  let example = find_example(&resource_dir)
    .ok_or_else(|| format!("config.example.yaml не найден в {}", resource_dir.display()))?;
  let home = std::env::var_os("HOME")
    .map(PathBuf::from)
    .ok_or("Переменная HOME не задана")?;
  let config_dir = home.join(".config").join("jarvis");
  let dest = config_dir.join("config.yaml");
  if !dest.exists() {
    std::fs::create_dir_all(&config_dir)
      .map_err(|e| format!("Не удалось создать {}: {e}", config_dir.display()))?;
    std::fs::copy(&example, &dest).map_err(|e| format!("Не удалось скопировать конфиг: {e}"))?;
  }
  if let Ok(mut slot) = app.state::<Arc<AppState>>().packaged_config.lock() {
    *slot = Some(dest);
  }
  Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .manage(Arc::new(AppState {
      bridge: Mutex::new(None),
      stdin: Mutex::new(None),
      child_pid: AtomicU32::new(0),
      started: AtomicBool::new(false),
      pending: Arc::new(Mutex::new(HashMap::new())),
      bridge_epoch: Arc::new(AtomicU64::new(0)),
      app: Arc::new(Mutex::new(None)),
      req_counter: AtomicU64::new(0),
      packaged_config: Mutex::new(None),
    }))
    .invoke_handler(tauri::generate_handler![backend_start, backend_stop, backend_status, backend_send_message, backend_configure, backend_list_models, backend_timers, backend_clear_history, backend_switch_session, backend_delete_session, backend_purge_session, backend_purge_all_sessions, backend_get_config, list_microphones, set_default_microphone, system_stats])
    .setup(|app| {
      // Лог и в release: без него warn! о несуществующем сайдкаре уходил
      // в никуда, а пользователь получал «Не удалось запустить Python
      // bridge» без диагностики.
      app.handle().plugin(
        tauri_plugin_log::Builder::default()
          .level(if cfg!(debug_assertions) {
            log::LevelFilter::Info
          } else {
            log::LevelFilter::Warn
          })
          .targets([
            tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::Stdout),
            tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::LogDir {
              file_name: Some("jarvis-ui".into()),
            }),
          ])
          .build(),
      )?;
      // AppHandle для событий стрима из reader-потока
      if let Ok(mut slot) = app.state::<Arc<AppState>>().app.lock() {
        *slot = Some(app.handle().clone());
      }
      if !cfg!(debug_assertions) {
        if let Err(e) = seed_user_config(app.handle()) {
          log::warn!("seed_user_config failed (non-fatal): {e}");
        }
      }
      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
