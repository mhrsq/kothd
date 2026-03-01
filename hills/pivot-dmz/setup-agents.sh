#!/bin/bash
set -e

echo "=== Setting up Hill 3 agent ==="

# Create Hill 3 agent script on host
cat > /tmp/hill3-agent.sh << 'EOF'
#!/bin/bash
export HILL_ID=3
export AGENT_TOKEN=agent-hill-3---api-gateway-4d13bcb67969459fb5214101bd119afb
export KOTH_SERVER=http://${KOTH_VPC_IP:-10.x.x.6}:8000
export REPORT_INTERVAL=10
export KING_FILE=/root/king.txt
export SLA_CHECK_PORT=8080
export SLA_CHECK_TYPE=http
while true; do
  /opt/koth/hill-agent
  sleep 5
done
EOF
chmod +x /tmp/hill3-agent.sh

# Create Hill 4 agent script on host
cat > /tmp/hill4-agent.sh << 'EOF'
#!/bin/bash
export HILL_ID=4
export AGENT_TOKEN=agent-hill-4---data-vault-c6dbac179161bc8c23bc2002e0c50035
export KOTH_SERVER=http://${KOTH_VPC_IP:-10.x.x.6}:8000
export REPORT_INTERVAL=10
export KING_FILE=/root/king.txt
export SLA_CHECK_PORT=27017
export SLA_CHECK_TYPE=tcp
while true; do
  /opt/koth/hill-agent
  sleep 5
done
EOF
chmod +x /tmp/hill4-agent.sh

echo "=== Copying scripts into containers ==="
docker cp /tmp/hill3-agent.sh hill3-api-gateway:/opt/koth/run-agent.sh
docker cp /tmp/hill4-agent.sh hill4-data-vault:/opt/koth/run-agent.sh

echo "=== Killing any existing agents ==="
docker exec hill3-api-gateway pkill -f hill-agent 2>/dev/null || true
docker exec hill4-data-vault pkill -f hill-agent 2>/dev/null || true
sleep 1

echo "=== Starting Hill 3 agent ==="
docker exec -d hill3-api-gateway bash -c 'nohup /opt/koth/run-agent.sh > /var/log/koth-agent.log 2>&1'
sleep 3

echo "Hill 3 agent PID:"
docker exec hill3-api-gateway pgrep -f hill-agent || echo "NOT RUNNING"

echo "=== Starting Hill 4 agent ==="
docker exec -d hill4-data-vault bash -c 'nohup /opt/koth/run-agent.sh > /var/log/koth-agent.log 2>&1'
sleep 3

echo "Hill 4 agent PID:"
docker exec hill4-data-vault pgrep -f hill-agent || echo "NOT RUNNING"

echo ""
echo "=== Hill 3 agent log ==="
docker exec hill3-api-gateway tail -10 /var/log/koth-agent.log 2>/dev/null || echo "no log"

echo "=== Hill 4 agent log ==="
docker exec hill4-data-vault tail -10 /var/log/koth-agent.log 2>/dev/null || echo "no log"

echo ""
echo "=== DONE ==="
