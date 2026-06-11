// Mirror of the backend slugify (api/storage/slug.py) for the create-project
// path preview. Display only; the server computes the authoritative slug.
export function slugify(value: string): string {
  const s = value
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return s || "untitled";
}
