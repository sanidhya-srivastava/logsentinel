import jenkins.model.Jenkins
import hudson.security.FullControlOnceLoggedInAuthorizationStrategy
import hudson.security.HudsonPrivateSecurityRealm
import hudson.security.csrf.DefaultCrumbIssuer
import jenkins.install.InstallState

def jenkins = Jenkins.get()
def adminId = System.getenv("JENKINS_ADMIN_ID") ?: "logsentinel"
def adminPassword = System.getenv("JENKINS_ADMIN_PASSWORD") ?: "logsentinel"

def securityRealm = new HudsonPrivateSecurityRealm(false)

if (securityRealm.getUser(adminId) == null) {
    securityRealm.createAccount(adminId, adminPassword)
}

jenkins.setSecurityRealm(securityRealm)

def authStrategy = new FullControlOnceLoggedInAuthorizationStrategy()
authStrategy.setAllowAnonymousRead(false)
jenkins.setAuthorizationStrategy(authStrategy)

if (jenkins.getCrumbIssuer() == null) {
    jenkins.setCrumbIssuer(new DefaultCrumbIssuer(true))
}

InstallState.INITIAL_SETUP_COMPLETED.initializeState()
jenkins.save()