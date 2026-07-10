import { useState } from 'react'
import { useChatStream } from '../hooks/useChatStream'
import { MessageList } from './MessageList'
import { Composer } from './Composer'

export function ChatPanel() {
  const { send, retry, stop } = useChatStream()
  const [draft, setDraft] = useState('')
  const [focusSignal, setFocusSignal] = useState(0)

  const handleSuggestion = (text: string) => {
    setDraft(text)
    setFocusSignal((n) => n + 1)
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <MessageList onRetry={(message) => void retry(message)} onSuggestion={handleSuggestion} />
      <Composer
        draft={draft}
        onDraftChange={setDraft}
        focusSignal={focusSignal}
        onSend={(message, options) => void send(message, options)}
        onStop={stop}
      />
    </div>
  )
}
