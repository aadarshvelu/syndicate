const _isDesktop = window.matchMedia(
  '(pointer: fine) and (hover: hover) and (min-width: 1024px)'
).matches

export function useDeviceType() {
  return { isDesktop: _isDesktop }
}
