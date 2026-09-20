#!/usr/bin/env bash

# This file is sourced, so it intentionally does not change the caller's
# shell options (notably nounset, which is incompatible with ROS setup files).

# Source this in every car and in the operator laptop. All participants must
# use the same domain while localhost-only mode must remain disabled.
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export ROS_LOCALHOST_ONLY=0
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
echo "ROS_DOMAIN_ID=${ROS_DOMAIN_ID}"
echo "ROS_LOCALHOST_ONLY=${ROS_LOCALHOST_ONLY}"
echo "RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION}"
