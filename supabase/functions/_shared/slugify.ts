/**
 * Common English stop words to filter out when generating short slugs.
 */
const STOP_WORDS = new Set([
  "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
  "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
  "be", "have", "has", "had", "do", "does", "did", "will", "would",
  "could", "should", "may", "might", "must", "shall", "can", "need",
  "it", "its", "this", "that", "these", "those", "i", "you", "he",
  "she", "we", "they", "what", "which", "who", "whom", "how", "when",
  "where", "why", "all", "each", "every", "both", "few", "more",
  "most", "other", "some", "such", "no", "not", "only", "same", "so",
  "than", "too", "very", "just", "also", "now", "here", "there",
  "show", "shorts", "video", "podcast", "episode", "part", "series",
]);

/**
 * Generate a URL-friendly slug from a title using smart abbreviation.
 * 
 * Extracts key words (skipping common stop words) and limits to a short,
 * memorable slug. Falls back to hash-based slug if no key words found.
 * 
 * @param title - The title to slugify
 * @param maxWords - Maximum number of key words to include (default: 3)
 * @param maxLength - Maximum slug length (default: 20)
 * @returns A short, URL-friendly slug
 * 
 * @example
 * slugifyShort("Meta Acquires the Fake Bot Social Network")
 * // Returns: "meta-acquires-fake-bot"
 * 
 * @example
 * slugifyShort("Your Agent, My Agent: Building Multi-Agent Systems")
 * // Returns: "your-agent-my-agent"
 */
export function slugifyShort(
  title: string,
  maxWords: number = 3,
  maxLength: number = 20,
): string {
  const words = title
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter((w) => w.length > 0 && !STOP_WORDS.has(w));

  if (words.length === 0) {
    return hashSlug(title);
  }

  const keyWords: string[] = [];
  let totalLength = 0;

  for (const word of words) {
    if (keyWords.length >= maxWords) break;
    if (totalLength + word.length + (keyWords.length > 0 ? 1 : 0) > maxLength) {
      break;
    }
    keyWords.push(word);
    totalLength += word.length + (keyWords.length > 1 ? 1 : 0);
  }

  if (keyWords.length === 0) {
    return hashSlug(title);
  }

  return keyWords.join("-");
}

/**
 * Generate a hash-based slug from a string.
 * Uses a simple hash function and encodes in base36.
 * 
 * @param str - The string to hash
 * @param length - Length of the hash (default: 6)
 * @returns A hash-based slug like "v-a3f8dk"
 */
export function hashSlug(str: string, length: number = 6): string {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash = hash & hash;
  }
  
  const hashStr = Math.abs(hash).toString(36);
  return `v-${hashStr.slice(0, length).padEnd(length, "0")}`;
}

/**
 * Traditional full slugify - converts title to URL-friendly format.
 * Kept for backwards compatibility with existing long slugs.
 * 
 * @param title - The title to slugify
 * @param maxLength - Maximum length (default: 80)
 * @returns A URL-friendly slug
 */
export function slugifyFull(title: string, maxLength: number = 80): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, maxLength);
}
