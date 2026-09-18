import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/Card";
import { DropdownOptionsTable } from "../shared/DropdownOptionsTable";

export default function CategoriesPage() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Categories</CardTitle>
        <p className="mt-1 text-xs text-mute">
          The 7 PRD categories plus &ldquo;Others&rdquo; are built-in and can&rsquo;t be removed. Add more below if
          Operations needs a category the PRD list doesn&rsquo;t cover.
        </p>
      </CardHeader>
      <CardBody>
        <DropdownOptionsTable scope="task_category" emptyLabel="No category options yet." />
      </CardBody>
    </Card>
  );
}
