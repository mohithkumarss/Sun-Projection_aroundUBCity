"use client";

/**
 * Error and empty-state surfaces.
 *
 * Every failure mode in the brief is represented explicitly. Nothing here
 * substitutes placeholder or fabricated content for missing data.
 */

export function TokenError({ message }: { message: string }) {
  return (
    <main className="grid min-h-screen place-items-center bg-background p-6">
      <div className="w-full max-w-lg border border-panel-border bg-panel p-6">
        <h1 className="text-lg font-semibold text-warn">
          Mapbox access token required
        </h1>
        <p className="mt-2 text-sm text-muted">{message}</p>
        <pre className="mt-4 overflow-x-auto border border-panel-border bg-[var(--background)] p-3 text-xs">
          {`# web/.env.local
NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN=pk.your_public_token_here

# then restart the dev server:  npm run dev`}
        </pre>
        <p className="mt-3 text-xs text-muted">
          The token is read from the environment and is never committed. Copy{" "}
          <code className="tnum">web/.env.example</code> to{" "}
          <code className="tnum">web/.env.local</code> to get started.
        </p>
      </div>
    </main>
  );
}

export function DatasetErrorPanel({
  title,
  message,
  detail,
}: {
  title: string;
  message: string;
  detail?: string;
}) {
  return (
    <main className="grid min-h-screen place-items-center bg-background p-6">
      <div className="w-full max-w-xl border border-panel-border bg-panel p-6">
        <h1 className="text-lg font-semibold text-warn">{title}</h1>
        <p className="mt-2 text-sm text-muted">{message}</p>
        {detail ? (
          <pre className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap border border-panel-border bg-[var(--background)] p-3 text-xs text-muted">
            {detail}
          </pre>
        ) : null}
        <p className="mt-4 text-xs text-muted">
          The application will not render substitute or sample data. Rebuild the
          research dataset from its real source:
        </p>
        <pre className="mt-2 overflow-x-auto border border-panel-border bg-[var(--background)] p-3 text-xs">
          python scripts/run_pipeline.py
        </pre>
      </div>
    </main>
  );
}

export function LoadingPanel() {
  return (
    <main className="grid min-h-screen place-items-center bg-background">
      <p className="tnum text-sm text-muted">
        Loading research dataset (25 frames)…
      </p>
    </main>
  );
}
