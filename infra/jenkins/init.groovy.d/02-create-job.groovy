import jenkins.model.Jenkins
import java.io.File
import java.io.ByteArrayInputStream

def jenkins = Jenkins.get()
def jobName = "logsentinel-pipeline"

if (jenkins.getItem(jobName) == null) {
    File configFile = new File("/usr/share/jenkins/ref/job-config.xml")
    if (!configFile.exists()) {
        configFile = new File("/var/jenkins_home/job-config.xml")
    }
    if (configFile.exists()) {
        def xml = configFile.text
        def xmlStream = new ByteArrayInputStream(xml.getBytes("UTF-8"))
        jenkins.createProjectFromXML(jobName, xmlStream)
        println("===> [LogSentinel] Successfully auto-created pipeline job: ${jobName}")
    } else {
        println("===> [LogSentinel] job-config.xml not found at ${configFile.path}")
    }
} else {
    println("===> [LogSentinel] Job ${jobName} already exists.")
}
