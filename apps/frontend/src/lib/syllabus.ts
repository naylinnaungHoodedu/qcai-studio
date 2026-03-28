import type { SourceAsset } from "@/lib/types";

export type SyllabusAssetGroups = {
  documentAssets: SourceAsset[];
  supplementalAssets: SourceAsset[];
};

export function splitSyllabusAssets(sourceAssets: SourceAsset[]): SyllabusAssetGroups {
  const documentAssets: SourceAsset[] = [];
  const supplementalAssets: SourceAsset[] = [];

  for (const asset of sourceAssets) {
    if (asset.kind.trim().toLowerCase() === "document") {
      documentAssets.push(asset);
    } else {
      supplementalAssets.push(asset);
    }
  }

  return { documentAssets, supplementalAssets };
}
