/** The approved symbol and outlined wordmark share the same source as our icons. */
export function BrandLockup() {
  return (
    <span className="brand-lockup">
      <img src="/brand/evodesign-lockup.svg?v=syne700-1" alt="EvoDesign" width="276" height="64" className="block h-auto w-full dark:hidden" />
      <img src="/brand/evodesign-lockup-dark.svg?v=syne700-1" alt="EvoDesign" width="276" height="64" className="hidden h-auto w-full dark:block" />
    </span>
  );
}

/** Wordmark-only lockup for placements that already display the app icon. */
export function BrandWordmark() {
  return (
    <span className="inline-block w-36 max-w-full align-middle">
      <img src="/brand/evodesign-wordmark.svg?v=syne700-1" alt="EvoDesign" width="200" height="48" className="block h-auto w-full dark:hidden" />
      <img src="/brand/evodesign-wordmark-dark.svg?v=syne700-1" alt="EvoDesign" width="200" height="48" className="hidden h-auto w-full dark:block" />
    </span>
  );
}
