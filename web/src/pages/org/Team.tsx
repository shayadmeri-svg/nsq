import { PageHeader } from "../../components/ui";
import { UserManager } from "../admin/UserManager";
import { useOrg } from "./common";

export function Team() {
  const { org, slug } = useOrg();
  return (
    <>
      <PageHeader eyebrow="Team" title={`People at ${org?.name ?? "…"}`} subtitle="Invite colleagues, set their role and persona, and remove access when they leave." />
      <UserManager orgSlug={slug} />
    </>
  );
}
