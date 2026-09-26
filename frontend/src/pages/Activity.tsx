import { Alert, Card, Space } from "antd";
import { ActivityTable } from "./Mrs";

export default function ActivityPage() {
  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Alert type="info" showIcon message="重新扫描只更新 Sonar 告警，不会运行 Agent 或新建会话。勾选告警并点击「指派给 Agent」后，新会话会出现在这里。" />
      <Card title="最近会话">
        <ActivityTable />
      </Card>
    </Space>
  );
}
