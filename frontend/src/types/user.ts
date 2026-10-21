export interface User {
  name: string
  email: string
  isAdmin: boolean
  // Keycloak groups from the token's `groups` claim (e.g. "/engineering") - offered when sharing.
  groups: string[]
}
