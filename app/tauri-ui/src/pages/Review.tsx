import { useEffect, useMemo, useState } from "react";
import { ipc, type ReviewDraft, type ReviewJob } from "../lib/ipc";
import { useT } from "../store";

type BusyAction = "prepare" | "save" | "approve" | "reject";

export default function ReviewPage() {
  const t = useT();
  const [items, setItems] = useState<ReviewJob[]>([]);
  const [stats, setStats] = useState({
    total: 0,
    totalCaptured: 0,
    totalEligible: 0,
    totalNeedsReview: 0,
    totalFiltered: 0,
  });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draftText, setDraftText] = useState("");
  const [busy, setBusy] = useState<BusyAction | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const selected = useMemo(
    () => items.find((item) => item.job.id === selectedId) ?? items[0] ?? null,
    [items, selectedId],
  );

  async function refresh(preferredId?: string) {
    setLoading(true);
    setError(null);
    try {
      const queue = await ipc.listReviewJobs(0, 30);
      setItems(queue.items);
      setStats({
        total: queue.total,
        totalCaptured: queue.totalCaptured,
        totalEligible: queue.totalEligible,
        totalNeedsReview: queue.totalNeedsReview,
        totalFiltered: queue.totalFiltered,
      });
      const nextId = preferredId ?? selectedId ?? queue.items[0]?.job.id ?? null;
      setSelectedId(nextId);
      const current = queue.items.find((item) => item.job.id === nextId) ?? queue.items[0];
      setDraftText(current?.draft?.content ?? "");
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  function selectJob(item: ReviewJob) {
    setSelectedId(item.job.id);
    setDraftText(item.draft?.content ?? "");
    setError(null);
    setNotice(null);
  }

  async function prepare() {
    if (!selected) return;
    setBusy("prepare");
    setError(null);
    setNotice(null);
    try {
      await ipc.prepareReviewJob(selected.job.id);
      await refresh(selected.job.id);
      setNotice(t("review.prepared"));
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(null);
    }
  }

  async function save() {
    if (!selected?.draft) return;
    setBusy("save");
    setError(null);
    setNotice(null);
    try {
      const draft = await ipc.updateReviewDraft(selected.draft.id, draftText);
      replaceDraft(draft);
      setDraftText(draft.content);
      setNotice(t("review.saved"));
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(null);
    }
  }

  async function decide(decision: "approve" | "reject") {
    if (!selected?.draft) return;
    const action = decision === "approve" ? "approve" : "reject";
    setBusy(action);
    setError(null);
    setNotice(null);
    try {
      let draft = selected.draft;
      if (draftText.trim() !== draft.content) {
        draft = await ipc.updateReviewDraft(draft.id, draftText);
      }
      const reviewed = await ipc.reviewDraft(draft.id, decision);
      replaceDraft(reviewed);
      setDraftText(reviewed.content);
      setNotice(t(decision === "approve" ? "review.approved" : "review.rejected"));
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(null);
    }
  }

  function replaceDraft(draft: ReviewDraft) {
    if (!selected) return;
    setItems((current) =>
      current.map((item) =>
        item.job.id === selected.job.id ? { ...item, draft } : item,
      ),
    );
  }

  const isDirty = Boolean(selected?.draft && draftText.trim() !== selected.draft.content);

  return (
    <div className="space-y-8">
      <div className="flex items-end justify-between border-b-4 border-[var(--ink)] pb-4">
        <div>
          <h2 className="text-5xl italic">{t("review.title")}</h2>
          <p className="mono-tag mt-2">{t("review.subtitle")}</p>
        </div>
        <div className="text-right">
          <span className="text-3xl font-mono">{stats.total}</span>
          <div className="mono-tag">{t("review.candidates")}</div>
          <div className="font-mono text-[10px] text-[var(--muted-fg)] mt-1">
            {t("review.filterSummary", {
              captured: stats.totalCaptured,
              filtered: stats.totalFiltered,
            })}
          </div>
        </div>
      </div>

      <div className="panel-invert flex items-center justify-between gap-4 py-4">
        <div>
          <div className="font-mono text-xs uppercase tracking-widest">{t("review.safetyTitle")}</div>
          <p className="text-sm mt-1 text-neutral-300">{t("review.safetyDesc")}</p>
        </div>
        <span className="border border-white px-3 py-1 font-mono text-[10px] uppercase tracking-widest whitespace-nowrap">
          Send Off
        </span>
      </div>

      {error && <div className="border-2 border-[var(--ink)] p-4 font-mono text-sm">{error}</div>}
      {notice && <div className="border border-[var(--ink)] p-3 font-mono text-sm">✓ {notice}</div>}

      {loading ? (
        <div className="mono-tag py-16 text-center">{t("common.loading")}</div>
      ) : items.length === 0 ? (
        <div className="panel py-16 text-center">
          <h3 className="text-2xl italic">
            {stats.totalCaptured > 0 ? t("review.noMatches") : t("review.empty")}
          </h3>
          <p className="text-sm text-[var(--muted-fg)] mt-3">
            {stats.totalCaptured > 0 ? t("review.noMatchesHint") : t("review.emptyHint")}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-[minmax(250px,0.85fr)_minmax(420px,1.6fr)] border border-[var(--ink)] min-h-[560px]">
          <aside className="border-b md:border-b-0 md:border-r border-[var(--ink)] max-h-64 md:max-h-[680px] overflow-auto">
            {items.map((item, index) => (
              <button
                key={item.job.id}
                onClick={() => selectJob(item)}
                className={[
                  "w-full text-left p-5 border-b border-[var(--border-light)] transition-colors",
                  selected?.job.id === item.job.id
                    ? "bg-[var(--ink)] text-[var(--paper)]"
                    : "hover:bg-[var(--muted)]",
                ].join(" ")}
              >
                <div className="flex justify-between gap-3 font-mono text-[10px] uppercase tracking-widest opacity-70">
                  <span>#{String(index + 1).padStart(2, "0")} · {item.job.platform === "linkedin" ? "LinkedIn" : "BOSS"}</span>
                  <ReviewBadge item={item} />
                </div>
                <h3 className="text-xl mt-3 leading-tight">{item.job.title || t("review.untitled")}</h3>
                <p className="text-sm mt-1 opacity-75">{item.job.company || "—"}</p>
                <div className="font-mono text-[10px] mt-4 opacity-60">
                  {[item.job.salary, item.job.location].filter(Boolean).join(" · ") || "—"}
                </div>
              </button>
            ))}
          </aside>

          {selected && (
            <section className="p-7 overflow-auto max-h-[680px]">
              <div className="flex items-start justify-between gap-6">
                <div>
                  <span className="mono-tag">
                    {selected.job.platform === "linkedin" ? "LinkedIn" : "BOSS"} · {selected.job.company || "—"}
                  </span>
                  <h3 className="text-3xl mt-1">{selected.job.title || t("review.untitled")}</h3>
                  <p className="font-mono text-xs mt-2 text-[var(--muted-fg)]">
                    {[selected.job.salary, selected.job.location].filter(Boolean).join(" · ") || "—"}
                  </p>
                </div>
                {selected.evaluation?.score != null && (
                  <div className="text-right border-l-4 border-[var(--ink)] pl-5">
                    <div className="font-mono text-4xl">{selected.evaluation.score}</div>
                    <div className="mono-tag">Match / 100</div>
                  </div>
                )}
              </div>

              {selected.evaluation && (
                <div className="bg-[var(--muted)] p-4 mt-6 text-sm">
                  <span className="field-label">{t("review.matchReason")}</span>
                  <p>{selected.evaluation.reason || t("review.noReason")}</p>
                  {selected.evaluation.degraded && (
                    <p className="font-mono text-xs mt-2">⚠ {t("review.degraded")}</p>
                  )}
                </div>
              )}

              <div className="border-l-4 border-[var(--ink)] pl-4 mt-6">
                <span className="field-label">{t("review.ruleResult")}</span>
                <p className="text-sm">{selected.ruleMatch.reasons.join(" · ")}</p>
                {selected.ruleMatch.state === "needs_review" && (
                  <p className="font-mono text-xs mt-2">⚠ {t("review.needsManualCheck")}</p>
                )}
              </div>

              <details className="mt-6 border-y border-[var(--ink)] py-3">
                <summary className="cursor-pointer font-mono text-xs uppercase tracking-widest">
                  {t("review.jd")}
                </summary>
                <p className="mt-4 whitespace-pre-wrap text-sm leading-7 max-h-56 overflow-auto">
                  {selected.job.description || t("review.noDescription")}
                </p>
              </details>

              {!selected.draft ? (
                <div className="mt-8 border-2 border-dashed border-[var(--ink)] p-8 text-center">
                  <h4 className="text-xl italic">{t("review.noDraft")}</h4>
                  <p className="text-sm text-[var(--muted-fg)] mt-2 mb-6">{t("review.noDraftHint")}</p>
                  <button className="btn" onClick={prepare} disabled={busy !== null}>
                    {busy === "prepare" ? t("review.preparing") : t("review.prepare")}
                  </button>
                </div>
              ) : (
                <div className="mt-7">
                  <div className="flex items-center justify-between">
                    <label className="field-label mb-0">{t("review.draft")}</label>
                    <span className="mono-tag">
                      {selected.draft.reviewState} · REV {selected.draft.revision}
                    </span>
                  </div>
                  <textarea
                    value={draftText}
                    onChange={(event) => setDraftText(event.target.value)}
                    className="w-full min-h-40 mt-3 border-2 border-[var(--ink)] p-4 bg-white text-base leading-7 resize-y focus-visible:outline-offset-2"
                  />
                  {!selected.draft.validationOk && (
                    <div className="mt-2 font-mono text-xs">
                      ⚠ {t("review.validationFailed")}: {selected.draft.validationReasons.join(", ")}
                    </div>
                  )}
                  <div className="flex flex-wrap gap-3 mt-5">
                    <button className="btn-outline" onClick={save} disabled={!isDirty || busy !== null}>
                      {busy === "save" ? t("btn.saving") : t("btn.save")}
                    </button>
                    <button
                      className="btn"
                      onClick={() => decide("approve")}
                      disabled={busy !== null || !draftText.trim()}
                    >
                      {busy === "approve" ? t("review.approving") : t("review.approve")}
                    </button>
                    <button
                      className="btn-ghost"
                      onClick={() => decide("reject")}
                      disabled={busy !== null}
                    >
                      {busy === "reject" ? t("review.rejecting") : t("review.reject")}
                    </button>
                  </div>
                </div>
              )}
            </section>
          )}
        </div>
      )}
    </div>
  );
}

function ReviewBadge({ item }: { item: ReviewJob }) {
  if (item.ruleMatch.state === "needs_review") return <span>Check</span>;
  if (!item.draft) return <span>Unprepared</span>;
  if (item.draft.reviewState === "approved") return <span>Approved</span>;
  if (item.draft.reviewState === "rejected") return <span>Rejected</span>;
  return <span>Pending</span>;
}
