/** Quiet geometric identity for the assistant, matching the cyan/violet studio palette. */
export function AssistantAvatar({ size = 26 }: { size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true">
    <circle cx="16" cy="11" r="8" fill="#9A89D9" fillOpacity=".8" />
    <circle cx="21" cy="16" r="8" fill="#83B7E5" fillOpacity=".8" />
    <circle cx="16" cy="21" r="8" fill="#73C4CA" fillOpacity=".75" />
    <circle cx="11" cy="16" r="8" fill="#8977D6" fillOpacity=".75" />
    <circle cx="16" cy="16" r="5" fill="#7160B4" fillOpacity=".65" />
  </svg>;
}
