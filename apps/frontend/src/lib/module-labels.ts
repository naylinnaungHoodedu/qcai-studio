import { MODULE_SLUGS } from "@/lib/site";

export function getModuleNumber(moduleSlug: string): number | null {
  const index = MODULE_SLUGS.indexOf(moduleSlug);
  return index >= 0 ? index + 1 : null;
}

export function formatModuleLabel(moduleNumber: number): string {
  return `Module ${moduleNumber}`;
}

export function getModuleLabel(moduleSlug: string): string | null {
  const moduleNumber = getModuleNumber(moduleSlug);
  return moduleNumber ? formatModuleLabel(moduleNumber) : null;
}
