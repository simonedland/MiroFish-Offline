import service from './index'

const BASE = '/api/simulation/sms'

export async function getAgents(simulationId) {
  return service.get(`${BASE}/agents`, { params: { simulation_id: simulationId } })
}

export async function getThreads(simulationId, phone) {
  return service.get(`${BASE}/threads/${phone}`, { params: { simulation_id: simulationId } })
}

export async function getThread(simulationId, phoneA, phoneB, round = null) {
  const params = { simulation_id: simulationId }
  if (round !== null) params.round = round
  return service.get(`${BASE}/thread/${phoneA}/${phoneB}`, { params })
}

export async function getSmsEvents(simulationId, since = 0) {
  return service.get(`${BASE}/events`, { params: { simulation_id: simulationId, since } })
}
