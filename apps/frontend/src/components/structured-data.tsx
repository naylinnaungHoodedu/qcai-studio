export function StructuredData({ data, id }: { data: Record<string, unknown> | Array<Record<string, unknown>>; id?: string }) {
  return (
    <script
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }}
      id={id}
      type="application/ld+json"
    />
  );
}
