const DB_NAME = 'jiayuan-imports'
const STORE_NAME = 'pending-files'
const SETTINGS_STORE = 'settings'

const openDb = () => new Promise((resolve, reject) => {
  const request = indexedDB.open(DB_NAME, 2)
  request.onupgradeneeded = () => {
    if (!request.result.objectStoreNames.contains(STORE_NAME)) request.result.createObjectStore(STORE_NAME, { keyPath: 'key' })
    if (!request.result.objectStoreNames.contains(SETTINGS_STORE)) request.result.createObjectStore(SETTINGS_STORE)
  }
  request.onsuccess = () => resolve(request.result)
  request.onerror = () => reject(request.error)
})

const transact = async (mode, handler) => {
  const db = await openDb()
  try {
    return await new Promise((resolve, reject) => {
      const transaction = db.transaction(STORE_NAME, mode)
      const store = transaction.objectStore(STORE_NAME)
      handler(store, resolve, reject)
      transaction.onerror = () => reject(transaction.error)
    })
  } finally { db.close() }
}

export const loadImportQueue = () => transact('readonly', (store, resolve, reject) => {
  const request = store.getAll()
  request.onsuccess = () => resolve(request.result || [])
  request.onerror = () => reject(request.error)
})

export const saveImportQueue = items => transact('readwrite', (store, resolve) => {
  store.clear()
  for (const item of items.filter(entry => entry.status !== 'ready')) {
    store.put({
      key: item.key,
      file: item.file,
      documentType: item.documentType,
      relativePath: item.relativePath || '',
      status: item.status === 'processing' ? 'queued' : item.status,
      error: item.error || '',
      estimate: item.estimate || null,
      duplicate: item.duplicate || null,
      versions: item.versions || [],
      targetFolderId: item.targetFolderId ?? null,
    })
  }
  store.transaction.oncomplete = () => resolve()
})

export const clearImportQueue = () => transact('readwrite', (store, resolve) => {
  store.clear().onsuccess = () => resolve()
})

export const saveWatchedDirectory = async handle => {
  const db = await openDb()
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(SETTINGS_STORE, 'readwrite')
    transaction.objectStore(SETTINGS_STORE).put(handle, 'watched-directory')
    transaction.oncomplete = () => { db.close(); resolve() }
    transaction.onerror = () => { db.close(); reject(transaction.error) }
  })
}

export const loadWatchedDirectory = async () => {
  const db = await openDb()
  return new Promise((resolve, reject) => {
    const request = db.transaction(SETTINGS_STORE, 'readonly').objectStore(SETTINGS_STORE).get('watched-directory')
    request.onsuccess = () => { db.close(); resolve(request.result || null) }
    request.onerror = () => { db.close(); reject(request.error) }
  })
}
