import type { ChatMessage } from '../store/chatStore'

export function UserMessage({ message }: { message: ChatMessage }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-tr-sm bg-stone-900 px-4 py-2.5 text-sm text-white shadow-sm dark:bg-zinc-100 dark:text-zinc-950">
        {message.content}
      </div>
    </div>
  )
}
