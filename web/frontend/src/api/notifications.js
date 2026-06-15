async function req(url, method = 'GET') {
  const res = await fetch(url, { method })
  if (res.status === 204) return null
  return res.json()
}

export const getNotifications  = ()  => req('/api/notifications')
export const markRead          = (id) => req(`/api/notifications/${id}/read`, 'POST')
export const markAllRead       = ()  => req('/api/notifications/read-all', 'POST')
export const deleteNotif       = (id) => req(`/api/notifications/${id}`, 'DELETE')
export const clearAll          = ()  => req('/api/notifications', 'DELETE')
