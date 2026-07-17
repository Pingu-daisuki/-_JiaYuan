const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('jiayuanDesktop', {
  exportPdf: payload => ipcRenderer.invoke('jiayuan:export-pdf', payload),
  tronClass: {
    open: config => ipcRenderer.invoke('tronclass:open', config),
    close: () => ipcRenderer.invoke('tronclass:close'),
    command: (command, config) => ipcRenderer.invoke('tronclass:command', { command, config }),
    status: () => ipcRenderer.invoke('tronclass:status'),
    onLog: callback => {
      const handler = (_event, message) => callback(message)
      ipcRenderer.on('tronclass:log', handler)
      return () => ipcRenderer.removeListener('tronclass:log', handler)
    },
    onStatus: callback => {
      const handler = (_event, status) => callback(status)
      ipcRenderer.on('tronclass:status-changed', handler)
      return () => ipcRenderer.removeListener('tronclass:status-changed', handler)
    },
  },
})
