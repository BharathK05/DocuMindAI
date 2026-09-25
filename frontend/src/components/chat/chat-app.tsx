"use client";

import { AnimatePresence, LazyMotion, domAnimation, m } from "motion/react";
import { FileText, LoaderCircle, PanelLeftOpen, SquarePen, UploadCloud } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";

import { ApiError, type Api } from "@/lib/api";
import { signOut, type SignedInUser } from "@/lib/auth";
import type {
  AccountFigures,
  ContextFigures,
  Conversation,
  DocumentOut,
  StoredMessage,
} from "@/lib/types";

import { Composer } from "./composer";
import { DocumentsDialog } from "./documents-dialog";
import { MessageView, type UiMessage } from "./messages";
import { Sidebar } from "./sidebar";
import { UsageBars } from "./usage-bars";
import { useAttachments } from "./use-attachments";
import { useSession } from "./use-session";

const DEFAULT_TITLE = "New conversation"; // the API's title until the first answer names it
const SUGGESTIONS = [
  "Summarize this document",
  "What are the key points?",
  "List the main requirements it sets out",
];

const toUi = (m: StoredMessage): UiMessage => ({
  key: `${m.index}`,
  role: m.role,
  content: m.content,
  citations: m.citations,
  status: "done",
});

const errorText = (err: unknown) =>
  err instanceof Error ? err.message : "Something went wrong. Try again.";

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh items-center justify-center p-6 text-muted">{children}</div>
  );
}

export function ChatApp() {
  const session = useSession();
  if (session.status === "loading") {
    return (
      <Centered>
        <LoaderCircle className="size-5 animate-spin" aria-label="Loading" />
      </Centered>
    );
  }
  if (session.status === "error") {
    return (
      <Centered>
        <p role="alert">Couldn&apos;t start DocuMind: {session.message}</p>
      </Centered>
    );
  }
  return <Chat api={session.api} user={session.user} />;
}

function Chat({ api, user }: { api: Api; user: SignedInUser }) {
  const router = useRouter();
  const activeId = useSearchParams().get("c");

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationsLoading, setConversationsLoading] = useState(true);
  const [documents, setDocuments] = useState<Map<string, DocumentOut>>(new Map());
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [threadLoading, setThreadLoading] = useState(false);
  const [threadError, setThreadError] = useState<string | null>(null);
  const [account, setAccount] = useState<AccountFigures | null>(null);
  const [context, setContext] = useState<ContextFigures | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [desktopSidebar, setDesktopSidebar] = useState(true);
  const [mobileSidebar, setMobileSidebar] = useState(false);
  const [documentsOpen, setDocumentsOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [editingTitle, setEditingTitle] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const createdRef = useRef<string | null>(null); // chat created locally: don't reload it
  const threadRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  const upsertDocument = useCallback((doc: DocumentOut) => {
    setDocuments((map) => new Map(map).set(doc.document_id, doc));
  }, []);
  const attach = useAttachments(api, upsertDocument);

  const active = conversations.find((c) => c.conversation_id === activeId) ?? null;
  const documentList = useMemo(
    () => [...documents.values()].sort((a, b) => b.created_at.localeCompare(a.created_at)),
    [documents],
  );

  // First load: chats and documents.
  useEffect(() => {
    api
      .listConversations()
      .then(setConversations)
      .catch(() => {})
      .finally(() => setConversationsLoading(false));
    api
      .listDocuments()
      .then((docs) => setDocuments(new Map(docs.map((d) => [d.document_id, d]))))
      .catch(() => {});
  }, [api]);

  // Open the chat named in the URL (?c=...), or a blank new chat.
  useEffect(() => {
    let cancelled = false;
    setThreadError(null);
    setEditingTitle(false);
    if (!activeId) {
      setMessages([]);
      setContext(null);
      api
        .usage()
        .then((u) => !cancelled && setAccount(u.account))
        .catch(() => {});
      return;
    }
    if (createdRef.current === activeId) {
      createdRef.current = null;
      return;
    }
    setMessages([]);
    setThreadLoading(true);
    Promise.all([api.getConversation(activeId), api.usage(activeId)])
      .then(([detail, usage]) => {
        if (cancelled) return;
        setMessages(detail.messages.map(toUi));
        setAccount(usage.account);
        setContext(usage.context);
        stickToBottom.current = true;
      })
      .catch((err) => {
        if (cancelled) return;
        setThreadError(
          err instanceof ApiError && err.status === 404
            ? "This chat doesn't exist, or it was deleted."
            : errorText(err),
        );
      })
      .finally(() => !cancelled && setThreadLoading(false));
    return () => {
      cancelled = true;
    };
  }, [activeId, api]);

  // Follow the answer as it streams in, unless the reader has scrolled up.
  useEffect(() => {
    const el = threadRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const openChat = useCallback(
    (id: string | null) => {
      abortRef.current?.abort();
      setMobileSidebar(false);
      attach.clear();
      router.push(id ? `/chat/?c=${id}` : "/chat/");
    },
    [attach, router],
  );

  const updateConversation = useCallback((id: string, changes: Partial<Conversation>) => {
    setConversations((list) => {
      const current = list.find((c) => c.conversation_id === id);
      if (!current) return list;
      const updated = { ...current, ...changes };
      // Most recently used first, like the API's ordering.
      return changes.updated_at
        ? [updated, ...list.filter((c) => c.conversation_id !== id)]
        : list.map((c) => (c.conversation_id === id ? updated : c));
    });
  }, []);

  async function send(question: string) {
    const readyIds = attach.attachments
      .filter((a) => a.status === "ready" && a.documentId)
      .map((a) => a.documentId as string);
    const userKey = crypto.randomUUID();
    const botKey = crypto.randomUUID();
    const patchBot = (fn: (m: UiMessage) => UiMessage) =>
      setMessages((list) => list.map((msg) => (msg.key === botKey ? fn(msg) : msg)));

    stickToBottom.current = true;
    setMessages((list) => [
      ...list,
      { key: userKey, role: "user", content: question, citations: [], status: "done" },
      { key: botKey, role: "assistant", content: "", citations: [], status: "streaming" },
    ]);
    const controller = new AbortController();
    abortRef.current = controller;
    setStreaming(true);

    try {
      let conversationId = activeId;
      let newDocuments = readyIds;
      if (!conversationId) {
        const created = await api.createConversation(readyIds);
        conversationId = created.conversation_id;
        newDocuments = []; // attached at creation
        createdRef.current = conversationId;
        setConversations((list) => [created, ...list]);
        router.push(`/chat/?c=${conversationId}`);
      } else if (readyIds.length) {
        const current = active?.document_ids ?? [];
        updateConversation(conversationId, {
          document_ids: [...new Set([...current, ...readyIds])],
        });
      }
      attach.clear();

      for await (const event of api.ask(
        question,
        conversationId,
        newDocuments,
        controller.signal,
      )) {
        switch (event.type) {
          case "sources":
            patchBot((msg) => ({ ...msg, citations: event.citations }));
            break;
          case "token":
            patchBot((msg) => ({ ...msg, content: msg.content + event.text }));
            break;
          case "done":
            patchBot((msg) => ({ ...msg, status: "done", notice: event.context.notice }));
            setAccount(event.account);
            setContext(event.context);
            updateConversation(conversationId, { updated_at: new Date().toISOString() });
            break;
          case "title":
            updateConversation(conversationId, { title: event.title });
            break;
          case "error":
            patchBot((msg) => ({ ...msg, status: "error", error: event.message }));
            break;
        }
      }
      patchBot((msg) =>
        msg.status === "streaming"
          ? { ...msg, status: "error", error: "The answer was cut off. Try again." }
          : msg,
      );
    } catch (err) {
      if (controller.signal.aborted) {
        patchBot((msg) => ({ ...msg, status: "stopped" }));
      } else {
        patchBot((msg) => ({ ...msg, status: "error", error: errorText(err) }));
      }
    } finally {
      setStreaming(false);
      if (abortRef.current === controller) abortRef.current = null;
    }
  }

  function retry(botKey: string) {
    const index = messages.findIndex((msg) => msg.key === botKey);
    const question = messages[index - 1];
    if (!question || question.role !== "user") return;
    setMessages((list) => list.filter((_, i) => i !== index && i !== index - 1));
    void send(question.content);
  }

  async function deleteChat(id: string) {
    try {
      await api.deleteConversation(id);
      setConversations((list) => list.filter((c) => c.conversation_id !== id));
      if (id === activeId) openChat(null);
    } catch (err) {
      window.alert(errorText(err));
    }
  }

  async function deleteDocument(id: string) {
    await api.deleteDocument(id);
    setDocuments((map) => {
      const next = new Map(map);
      next.delete(id);
      return next;
    });
  }

  async function rename(title: string) {
    setEditingTitle(false);
    const clean = title.trim();
    if (!active || !clean || clean === active.title) return;
    updateConversation(active.conversation_id, { title: clean });
    try {
      await api.renameConversation(active.conversation_id, clean);
    } catch {
      updateConversation(active.conversation_id, { title: active.title });
    }
  }

  function toggleSidebar() {
    if (window.matchMedia("(min-width: 1024px)").matches) setDesktopSidebar((v) => !v);
    else setMobileSidebar((v) => !v);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    const files = [...e.dataTransfer.files];
    if (files.length) attach.addFiles(files);
  }

  const sidebar = (
    <Sidebar
      conversations={conversations}
      activeId={activeId}
      userLabel={user.label}
      loading={conversationsLoading}
      onNewChat={() => openChat(null)}
      onSelect={openChat}
      onDelete={(id) => void deleteChat(id)}
      onOpenDocuments={() => setDocumentsOpen(true)}
      onSignOut={() => void signOut().finally(() => router.replace("/login/"))}
      onClose={toggleSidebar}
    />
  );

  const chatDocuments = (active?.document_ids ?? [])
    .map((id) => documents.get(id))
    .filter((d): d is DocumentOut => Boolean(d));
  const isEmpty = !activeId && messages.length === 0;
  const readyAttachment = attach.attachments.some((a) => a.status === "ready");
  const title = !active || active.title === DEFAULT_TITLE ? "New chat" : active.title;

  const composer = (
    <Composer
      attachments={attach.attachments}
      documents={documentList}
      chatDocumentIds={active?.document_ids ?? []}
      streaming={streaming}
      disabledReason={threadError ? "Open another chat to continue." : null}
      autoFocus={isEmpty}
      onFiles={attach.addFiles}
      onPickExisting={(d) => attach.addExisting([d])}
      onRemoveAttachment={attach.remove}
      onSend={(text) => void send(text)}
      onStop={() => abortRef.current?.abort()}
    />
  );

  return (
    <LazyMotion features={domAnimation} strict>
      <div className="flex h-dvh overflow-hidden">
        {/* Desktop: a column that can be collapsed. */}
        <aside
          className={`hidden shrink-0 overflow-hidden border-r border-line transition-[width] duration-300 lg:block ${
            desktopSidebar ? "w-72" : "w-0 border-r-0"
          }`}
        >
          <div className="h-full w-72">{sidebar}</div>
        </aside>

        {/* Phones and tablets: a drawer over the chat. */}
        <AnimatePresence>
          {mobileSidebar && (
            <>
              <m.div
                className="fixed inset-0 z-40 bg-ink/30 lg:hidden"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                onClick={() => setMobileSidebar(false)}
              />
              <m.aside
                className="fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw] shadow-2xl lg:hidden"
                initial={{ x: "-100%" }}
                animate={{ x: 0 }}
                exit={{ x: "-100%" }}
                transition={{ type: "spring", damping: 30, stiffness: 300 }}
              >
                {sidebar}
              </m.aside>
            </>
          )}
        </AnimatePresence>

        <main
          className="relative flex min-w-0 flex-1 flex-col"
          onDragOver={(e) => {
            if ([...e.dataTransfer.types].includes("Files")) {
              e.preventDefault();
              setDragging(true);
            }
          }}
          onDragLeave={(e) => e.currentTarget === e.target && setDragging(false)}
          onDrop={onDrop}
        >
          <header className="flex h-14 shrink-0 items-center gap-2 border-b border-line px-3 sm:px-4">
            <button
              type="button"
              onClick={toggleSidebar}
              aria-label="Open sidebar"
              className={`rounded-lg p-1.5 text-muted hover:bg-ink/5 hover:text-ink ${desktopSidebar ? "lg:hidden" : ""}`}
            >
              <PanelLeftOpen className="size-4.5" aria-hidden />
            </button>
            {!desktopSidebar && (
              <button
                type="button"
                onClick={() => openChat(null)}
                aria-label="New chat"
                className="hidden rounded-lg p-1.5 text-muted hover:bg-ink/5 hover:text-ink lg:block"
              >
                <SquarePen className="size-4.5" aria-hidden />
              </button>
            )}
            <div className="min-w-0 flex-1">
              {editingTitle && active ? (
                <input
                  autoFocus
                  defaultValue={active.title}
                  maxLength={120}
                  aria-label="Chat title"
                  onBlur={(e) => void rename(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void rename(e.currentTarget.value);
                    if (e.key === "Escape") setEditingTitle(false);
                  }}
                  className="w-full max-w-md rounded-lg border border-line-strong bg-card px-2 py-1 text-sm outline-none"
                />
              ) : (
                <button
                  type="button"
                  disabled={!active}
                  onClick={() => setEditingTitle(true)}
                  title={active ? "Rename chat" : undefined}
                  className="max-w-full truncate rounded-lg px-2 py-1 text-sm font-medium enabled:hover:bg-ink/5"
                >
                  {title}
                </button>
              )}
            </div>
            <UsageBars context={context} account={account} />
          </header>

          {isEmpty ? (
            <div className="flex flex-1 flex-col items-center justify-center overflow-y-auto px-4 pb-16">
              <m.div
                className="w-full max-w-2xl"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5 }}
              >
                <h1 className="mb-8 text-center font-display text-4xl tracking-tight sm:text-5xl">
                  What would you like to <span className="text-accent italic">know</span>?
                </h1>
                {composer}
                {readyAttachment && (
                  <ul className="mt-4 flex flex-wrap justify-center gap-2" aria-label="Suggestions">
                    {SUGGESTIONS.map((s) => (
                      <li key={s}>
                        <button
                          type="button"
                          onClick={() => void send(s)}
                          disabled={streaming}
                          className="rounded-full border border-line bg-card px-3.5 py-1.5 text-sm text-muted transition-colors hover:border-line-strong hover:text-ink"
                        >
                          {s}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="mt-6 text-center text-xs text-muted">
                  Attach PDFs with the paperclip or drop them here. Each answer cites its pages.
                </p>
              </m.div>
            </div>
          ) : (
            <>
              <div
                ref={threadRef}
                onScroll={(e) => {
                  const el = e.currentTarget;
                  stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
                }}
                className="flex-1 overflow-y-auto"
              >
                <div className="mx-auto w-full max-w-3xl px-4 pt-6 pb-10 sm:px-6">
                  {chatDocuments.length > 0 ? (
                    <ul className="mb-8 flex flex-wrap gap-2" aria-label="PDFs in this chat">
                      {chatDocuments.map((d) => (
                        <li
                          key={d.document_id}
                          className="flex items-center gap-1.5 rounded-full border border-line bg-card px-3 py-1 text-xs text-muted"
                        >
                          <FileText className="size-3.5 text-accent" aria-hidden />
                          <span className="max-w-52 truncate">{d.filename}</span>
                        </li>
                      ))}
                    </ul>
                  ) : active && !threadLoading ? (
                    <p className="mb-8 text-xs text-muted">Searching all your documents.</p>
                  ) : null}

                  {threadLoading && (
                    <div className="flex justify-center py-10 text-muted">
                      <LoaderCircle className="size-5 animate-spin" aria-label="Loading chat" />
                    </div>
                  )}
                  {threadError && (
                    <p
                      role="alert"
                      className="rounded-xl bg-danger/5 px-4 py-3 text-sm text-danger"
                    >
                      {threadError}
                    </p>
                  )}

                  <div className="space-y-8" aria-live="polite" aria-busy={streaming}>
                    {messages.map((msg, i) => (
                      <MessageView
                        key={msg.key}
                        message={msg}
                        question={messages[i - 1]?.content ?? ""}
                        onRetry={msg.status === "error" ? () => retry(msg.key) : undefined}
                      />
                    ))}
                  </div>
                </div>
              </div>
              <div className="shrink-0 px-3 pb-3 sm:px-4 sm:pb-4">
                <div className="mx-auto w-full max-w-3xl">
                  {composer}
                  <p className="mt-2 text-center text-[0.7rem] text-muted">
                    Answers come only from your documents. Check the cited pages for anything
                    important.
                  </p>
                </div>
              </div>
            </>
          )}

          {dragging && (
            <div className="pointer-events-none absolute inset-3 z-30 flex flex-col items-center justify-center gap-2 rounded-card border-2 border-dashed border-accent bg-paper/90 text-accent">
              <UploadCloud className="size-8" aria-hidden />
              <p className="font-medium">Drop PDFs to attach them</p>
            </div>
          )}
        </main>

        <DocumentsDialog
          open={documentsOpen}
          documents={documentList}
          onClose={() => setDocumentsOpen(false)}
          onDelete={deleteDocument}
        />
      </div>
    </LazyMotion>
  );
}
