import { useEffect, useRef } from "react";
import type { Collection } from "../../lib/api";
import { useChat, useSendChat } from "../../lib/queries";
import { Spinner } from "../../components/Spinner";

// Conversational box to request general changes or ask questions about the doc (05).
// One message → one response; the reply + any body revision arrive via the
// operations stream while the doc shows its in-progress state.
export function ChatPanel({
  collection,
  entryId,
  value,
  onChange,
  busy,
}: {
  collection: Collection;
  entryId: string;
  value: string;
  onChange: (v: string) => void;
  busy: boolean; // an operation is running on this doc
}) {
  const { data: chat } = useChat(collection, entryId);
  const send = useSendChat();
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat?.messages.length, busy]);

  const submit = () => {
    if (!value.trim() || busy || send.isPending) return;
    send.mutate({ collection, id: entryId, message: value.trim() });
    onChange("");
  };

  const messages = chat?.messages ?? [];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 space-y-2 overflow-auto p-3">
        {messages.length === 0 && (
          <p className="text-sm text-slate-400">
            Ask a question or request changes to this document.
          </p>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            className={`rounded-lg px-3 py-2 text-sm ${
              m.role === "user"
                ? "ml-6 bg-blue-600 text-white"
                : "mr-6 bg-white text-slate-700 ring-1 ring-slate-200"
            }`}
          >
            {m.content}
            {m.revisedBody && (
              <div className="mt-1 text-xs italic opacity-70">✎ edited the document</div>
            )}
          </div>
        ))}
        {busy && (
          <div className="mr-6 flex items-center gap-2 rounded-lg bg-white px-3 py-2 text-sm text-slate-500 ring-1 ring-slate-200">
            <Spinner /> thinking…
          </div>
        )}
        <div ref={endRef} />
      </div>
      <div className="border-t border-slate-200 p-2">
        <textarea
          className="w-full resize-none rounded-md border border-slate-300 p-2 text-sm focus:border-blue-500 focus:outline-none"
          rows={3}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
          }}
          placeholder="Message the AI about this doc…  (⌘/Ctrl+Enter to send)"
        />
        <button
          className="mt-1 w-full rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          onClick={submit}
          disabled={!value.trim() || busy || send.isPending}
        >
          Send
        </button>
      </div>
    </div>
  );
}
