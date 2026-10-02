/**
 * Mapbox access-token handling.
 *
 * The token is never hardcoded. It is read from
 * NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN and validated at runtime so a missing token
 * produces an explicit, actionable error instead of a blank grey canvas.
 */

export const MAPBOX_TOKEN_ENV = "NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN";

export interface TokenStatus {
  token: string | null;
  valid: boolean;
  /** Actionable message shown to the user when the token is unusable. */
  message: string | null;
}

/**
 * A Mapbox public token is a `pk.`-prefixed JWT-like string. This is a
 * structural check only - it cannot tell whether the token is valid,
 * authorised for the styles used, or within its URL quota.
 */
export function inspectToken(
  token: string | null | undefined,
): TokenStatus {
  if (!token || token.trim().length === 0) {
    return {
      token: null,
      valid: false,
      message:
        `Mapbox access token is not set. Set ${MAPBOX_TOKEN_ENV} in web/.env.local ` +
        "(copy web/.env.example) and restart the dev server.",
    };
  }

  const trimmed = token.trim();
  if (!trimmed.startsWith("pk.")) {
    return {
      token: trimmed,
      valid: false,
      message:
        `${MAPBOX_TOKEN_ENV} does not look like a Mapbox public token ` +
        `(expected a value beginning with "pk."). A secret "sk." token must not be used here.`,
    };
  }

  return { token: trimmed, valid: true, message: null };
}

export const MAPBOX_STYLE_LIGHT = "mapbox://styles/mapbox/light-v11";
