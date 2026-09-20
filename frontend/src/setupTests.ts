import "@testing-library/jest-dom";

// jsdom lacks these; Radix + the ThemeProvider rely on them in tests.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
}
if (!("ResizeObserver" in window)) {
  (window as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
// Node's native Web Storage global (stable as of Node 22+) shadows jsdom's window.localStorage
// with a non-functional stub in this jsdom/Node combination — `getItem`/`setItem`/`clear` are
// missing entirely. Install a plain in-memory Storage unconditionally, via defineProperty (never
// reading the existing accessor), so we never trip Node's native getter and its process warning.
const localStorageStore = new Map<string, string>();
const memoryLocalStorage: Storage = {
  getItem: (key: string) => (localStorageStore.has(key) ? (localStorageStore.get(key) as string) : null),
  setItem: (key: string, value: string) => {
    localStorageStore.set(key, String(value));
  },
  removeItem: (key: string) => {
    localStorageStore.delete(key);
  },
  clear: () => {
    localStorageStore.clear();
  },
  key: (index: number) => Array.from(localStorageStore.keys())[index] ?? null,
  get length() {
    return localStorageStore.size;
  },
};
Object.defineProperty(window, "localStorage", {
  value: memoryLocalStorage,
  configurable: true,
  writable: true,
});
