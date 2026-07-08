if [ -f ~/.bashrc ]; then
  source ~/.bashrc
fi

if [ -f /opt/ros/humble/setup.bash ]; then
  source /opt/ros/humble/setup.bash
fi

if [ -f "$PWD/install/setup.bash" ]; then
  source "$PWD/install/setup.bash"
fi
