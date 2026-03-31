type DisclosureGroup = {
  removeAttribute(name: string): void;
};

type DisclosureContainer = {
  querySelectorAll(selector: string): Iterable<DisclosureGroup>;
};

export function closeOpenNavGroups(container: DisclosureContainer | null) {
  if (!container) {
    return;
  }

  for (const group of container.querySelectorAll("details[open]")) {
    group.removeAttribute("open");
  }
}
