import service, { requestWithRetry } from './index'

/**
 * Parse a free-form scenario description into a ScenarioDefinition preview.
 * @param {string} description
 */
export const parseScenario = (description) => {
  return requestWithRetry(
    () => service.post('/api/scenario/parse', { description }),
    2,
    1000
  )
}

/**
 * Create a simulation from a description (non-blocking — fires background thread).
 * @param {Object} data - { description }
 */
export const createScenario = (data) => {
  return service.post('/api/scenario/create', data)
}

/**
 * Get the ScenarioDefinition (groups) for a simulation.
 * @param {string} simulationId
 */
export const getSimulationGroups = (simulationId) => {
  return service.get(`/api/simulation/${simulationId}/groups`)
}
