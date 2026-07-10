import { AppShell } from './app/AppShell'

// ThemeProvider (and QueryClientProvider) wrap this from main.tsx — App is
// just the composition root over the chat + preview shell.
function App() {
  return <AppShell />
}

export default App
