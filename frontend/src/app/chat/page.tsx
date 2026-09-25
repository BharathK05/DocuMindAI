import type { Metadata } from "next";
import { Suspense } from "react";

import { ChatApp } from "@/components/chat/chat-app";

export const metadata: Metadata = { title: "Chat" };

export default function ChatPage() {
  // ChatApp reads ?c=<conversation id>; a static export needs the Suspense boundary for that.
  return (
    <Suspense>
      <ChatApp />
    </Suspense>
  );
}
