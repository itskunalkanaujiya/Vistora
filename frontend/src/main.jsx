import './lib/renameStorage.js'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import BoardPage from './components/BoardPage.jsx'
import { boardIdFromAddress } from './lib/boards.js'

const boardId = boardIdFromAddress()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {boardId ? <BoardPage id={boardId} /> : <App />}
  </StrictMode>,
)
