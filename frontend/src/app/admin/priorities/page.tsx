import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { DropdownOptionsTable } from "../shared/DropdownOptionsTable";

export default function PrioritiesPage() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Priorities</CardTitle>
        <p className="mt-1 text-xs text-mute">Normal and Expedite are built-in and can&rsquo;t be removed.</p>
      </CardHeader>
      <CardBody>
        <DropdownOptionsTable scope="task_priority" emptyLabel="No priority options yet." />
      </CardBody>
    </Card>
  );
}
