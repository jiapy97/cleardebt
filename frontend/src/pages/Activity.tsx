import { Card } from "antd";
import { ActivityTable } from "./Mrs";

export default function ActivityPage() {
  return (
    <Card title="最近会话">
      <ActivityTable />
    </Card>
  );
}
