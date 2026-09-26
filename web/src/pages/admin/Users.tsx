import { PageHeader } from "../../components/ui";
import { UserManager } from "./UserManager";

export function Users() {
  return (
    <>
      <PageHeader eyebrow="Platform" title="Users & access" subtitle="Every account on the platform. Super admins run data jobs; platform admins manage organisations; org admins manage their own team; members view their organisation." />
      <UserManager />
    </>
  );
}
