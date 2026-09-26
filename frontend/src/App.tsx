import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { PageContainer, ProLayout } from "@ant-design/pro-components";
import { Alert, Button, Card } from "antd";
import {
  AuditOutlined,
  BranchesOutlined,
  ControlOutlined,
  HistoryOutlined,
  SettingOutlined,
  ThunderboltOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import AssignPage from "./pages/Assign";
import ControlsPage from "./pages/Controls";
import RulesPage from "./pages/Rules";
import MrsPage from "./pages/Mrs";
import ActivityPage from "./pages/Activity";
import SheetPage from "./pages/Sheet";
import SetupPage from "./pages/Setup";
import { useOverview } from "./lib/useOverview";

const qc = new QueryClient();

const menus = [
  { path: "assign", name: "指派给 Agent", icon: <ThunderboltOutlined /> },
  { path: "controls", name: "开关与日程", icon: <ControlOutlined /> },
  { path: "mrs", name: "请求修复", icon: <BranchesOutlined /> },
  { path: "activity", name: "Agent 活动", icon: <HistoryOutlined /> },
  { path: "sheet", name: "清算单", icon: <AuditOutlined /> },
  { path: "rules", name: "规则管理", icon: <UnorderedListOutlined /> },
  { path: "setup", name: "接入配置", icon: <SettingOutlined /> },
];

const pageMeta: Record<string, { title: string; sub: string; node: React.ReactNode }> = {
  assign: { title: "指派给 Agent", sub: "勾选主分支上的可修告警，不必等定时", node: <AssignPage /> },
  controls: { title: "开关与日程", sub: "点一下立即生效，下一轮照着做", node: <ControlsPage /> },
  mrs: { title: "请求修复", sub: "质量门失败的合并请求，开出打向原源分支的修复请求", node: <MrsPage /> },
  activity: { title: "Agent 活动", sub: "最近会话，每 10 秒自动刷新", node: <ActivityPage /> },
  sheet: { title: "清算单", sub: "最近一轮的决策与建议片段", node: <SheetPage /> },
  rules: { title: "规则管理", sub: "查看 Sonar 规则与可修清单，维护中文名", node: <RulesPage /> },
  setup: { title: "接入配置", sub: "地址、令牌和允许修改的仓库", node: <SetupPage /> },
};

const validPages = new Set(Object.keys(pageMeta));

function pageFromHash(): string {
  const key = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  return validPages.has(key) ? key : "assign";
}

function Shell() {
  const [page, setPage] = useState(pageFromHash);
  useEffect(() => {
    const onHash = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const go = (key: string) => {
    if (`#/${key}` !== window.location.hash) window.location.hash = `#/${key}`;
    else setPage(key);
  };
  const { data: overview, isLoading, isError, refetch } = useOverview();
  const meta = pageMeta[page];
  return (
    <ProLayout
      title="ClearDebt"
      logo="/static/console/logo.svg"
      layout="mix"
      splitMenus={false}
      navTheme="light"
      contentWidth="Fluid"
      route={{ path: "/", routes: menus }}
      location={{ pathname: `/${page}` }}
      menuItemRender={(item, dom) => (
        <a
          onClick={() => {
            const key = (item.path || "/").replace("/", "") || "assign";
            go(validPages.has(key) ? key : "assign");
          }}
        >
          {dom}
        </a>
      )}
      onMenuHeaderClick={() => go("assign")}
      avatarProps={{
        title: overview?.configured ? "已接入" : "未接入",
      }}
    >
      <PageContainer title={meta.title} subTitle={meta.sub}>
        {isLoading && (
          <Card loading style={{ minHeight: 200 }} />
        )}
        {isError && (
          <Alert
            type="error"
            showIcon
            message="连不上后端（http://127.0.0.1:8000），页面是空的"
            description="服务可能正在重启。等几秒后点重试，不用整页刷新。"
            action={
              <Button size="small" onClick={() => refetch()}>
                重试
              </Button>
            }
          />
        )}
        {!isLoading && !isError &&
          (Object.keys(pageMeta) as Array<keyof typeof pageMeta>).map((key) => (
            <div key={key} style={{ display: key === page ? "block" : "none" }}>
              {pageMeta[key].node}
            </div>
          ))}
      </PageContainer>
    </ProLayout>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <ConfigProvider locale={zhCN}>
        <Shell />
      </ConfigProvider>
    </QueryClientProvider>
  );
}
