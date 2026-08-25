import { useEffect } from "react";
import TitleBar from "./components/TitleBar";
import Sidebar from "./components/Sidebar";
import ChatTab from "./tabs/ChatTab";
import SettingsTab from "./tabs/SettingsTab";
import StatusTab from "./tabs/StatusTab";
import HistoryTab from "./tabs/HistoryTab";
import { useTab } from "./hooks/useTab";
import { useTheme } from "./hooks/useTheme";

export default function App() {
  const { tab, setTab } = useTab();
  const { theme } = useTheme();

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  return (
    <div className="flex h-screen w-screen flex-col bg-bg text-text">
      <TitleBar />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar tab={tab} setTab={setTab} />
        <main className="flex-1 overflow-hidden">
          {tab === "chat" && <ChatTab />}
          {tab === "settings" && <SettingsTab />}
          {tab === "status" && <StatusTab />}
          {tab === "history" && <HistoryTab />}
        </main>
      </div>
    </div>
  );
}
