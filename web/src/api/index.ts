import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

api.interceptors.response.use(
  (r) => r.data,
  (err) => Promise.reject(err)
)

export default api
