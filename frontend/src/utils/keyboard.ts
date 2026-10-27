/** Enter used to commit IME text must never submit a model request. */
export function shouldSubmitOnEnter(event: {
  key: string;
  shiftKey?: boolean;
  keyCode?: number;
  nativeEvent?: { isComposing?: boolean; keyCode?: number };
}): boolean {
  return event.key === 'Enter' && !event.shiftKey && !event.nativeEvent?.isComposing
    && event.keyCode !== 229 && event.nativeEvent?.keyCode !== 229;
}

/** Multiline creation forms require an explicit shortcut to start generation. */
export function shouldSubmitOnModifiedEnter(event: Parameters<typeof shouldSubmitOnEnter>[0] & {
  metaKey?: boolean;
  ctrlKey?: boolean;
}): boolean {
  return Boolean(event.metaKey || event.ctrlKey) && shouldSubmitOnEnter(event);
}
