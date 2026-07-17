const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('jiayuanDesktop', {
  exportPdf: payload => ipcRenderer.invoke('jiayuan:export-pdf', payload),
})
