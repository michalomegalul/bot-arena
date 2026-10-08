import { useEffect, useState } from "react";

export type Async<T> = { data: T | undefined; error: Error | undefined; loading: boolean };

/** Run an async loader whenever `deps` change; ignores results from stale requests. */
export function useAsync<T>(load: () => Promise<T>, deps: unknown[]): Async<T> & { setData: (v: T) => void } {
  const [state, setState] = useState<Async<T>>({ data: undefined, error: undefined, loading: true });
  useEffect(() => {
    let current = true;
    setState((s) => ({ ...s, loading: true, error: undefined }));
    load().then(
      (data) => current && setState({ data, error: undefined, loading: false }),
      (error: unknown) =>
        current && setState({ data: undefined, error: error instanceof Error ? error : new Error(String(error)), loading: false }),
    );
    return () => {
      current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { ...state, setData: (data: T) => setState({ data, error: undefined, loading: false }) };
}

/** Changes whenever the OS switches between light and dark, so canvas charts can recolour. */
export function useColorScheme(): "dark" | "light" {
  const query = "(prefers-color-scheme: light)";
  const [scheme, setScheme] = useState<"dark" | "light">(() => (matchMedia(query).matches ? "light" : "dark"));
  useEffect(() => {
    const mq = matchMedia(query);
    const onChange = () => setScheme(mq.matches ? "light" : "dark");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return scheme;
}

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => matchMedia(query).matches);
  useEffect(() => {
    const mq = matchMedia(query);
    const onChange = () => setMatches(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}
