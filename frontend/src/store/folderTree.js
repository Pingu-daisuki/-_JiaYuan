const normalizeId = (value) => {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 0
}

export const buildFolderTree = (folders = []) => {
  const root = { id: 0, value: 0, label: '根目录', children: [] }
  const lookup = new Map()
  const sourceLookup = new Map()

  for (const folder of folders) {
    const id = normalizeId(folder.id)
    if (!id || lookup.has(id)) continue
    lookup.set(id, { id, value: id, label: folder.course_name, children: [] })
    sourceLookup.set(id, folder)
  }

  const hasParentCycle = (id, parentId) => {
    const visited = new Set([id])
    let currentId = parentId
    while (currentId) {
      if (visited.has(currentId)) return true
      visited.add(currentId)
      currentId = normalizeId(sourceLookup.get(currentId)?.parent_id)
    }
    return false
  }

  for (const [id, node] of lookup) {
    const parentId = normalizeId(sourceLookup.get(id)?.parent_id)
    const parent = lookup.get(parentId)
    if (parent && !hasParentCycle(id, parentId)) parent.children.push(node)
    else root.children.push(node)
  }

  return [root]
}
