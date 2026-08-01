import { useCallback, useEffect, useState } from "react";

import {
  fetchChapterLinks,
  LoomUnreachableError,
  type ChapterLinks,
} from "../api/writerEvents";

/**
 * Which Loom chapters reference each of these events (LOOM-32).
 *
 * Fetched once for the whole set rather than per card. Deliberately NOT
 * cached across mounts: the entire point of the seam is that these numbers
 * track Loom, and a cache would reintroduce exactly the staleness the epic
 * removed — an event showing "Ch. 3" long after it became Ch. 4.
 *
 * `unreachable` is separate from an empty result on purpose. "Loom is closed"
 * and "this event is referenced nowhere" look identical as an absent chip, and
 * only one of them is a fact about the story.
 */
export function useChapterLinks(
  ids: string[],
  /** Which side of the seam to ask. Events and characters have identical
   *  shapes and identical failure modes, so they share this hook rather than
   *  growing two copies that drift. */
  fetcher: (ids: string[]) => Promise<ChapterLinks> = fetchChapterLinks,
) {
  const [links, setLinks] = useState<ChapterLinks>({});
  const [unreachable, setUnreachable] = useState(false);
  const [loading, setLoading] = useState(false);

  // Joined so the effect re-runs when the SET changes, not on every render
  // that happens to rebuild the array.
  const key = ids.join(",");

  const load = useCallback(async () => {
    if (!key) {
      setLinks({});
      setUnreachable(false);
      return;
    }
    setLoading(true);
    try {
      setLinks(await fetcher(key.split(",")));
      setUnreachable(false);
    } catch (err) {
      if (err instanceof LoomUnreachableError) {
        setUnreachable(true);
        setLinks({});
      }
      // Anything else is a bug on our side; the chips just stay absent rather
      // than claiming Loom is down when it is not.
    } finally {
      setLoading(false);
    }
  }, [key, fetcher]);

  useEffect(() => {
    void load();
  }, [load]);

  return { links, unreachable, loading, reload: load };
}
