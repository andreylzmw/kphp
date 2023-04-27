[build/buster/g++/c++17/asan=off/ubsan=off-1  ] 🚀  Start image=catthehacker/ubuntu:act-latest
[build/focal/clang++/c++17/asan=off/ubsan=on-2] 🚀  Start image=catthehacker/ubuntu:act-latest
[build/macos/clang++/c++17                    ] 🚧  Skipping unsupported platform -- Try running with `-P macos-12=...`
[build/jammy/g++/c++20/asan=on/ubsan=off-4    ] 🚀  Start image=catthehacker/ubuntu:act-latest
[build/focal/g++-10/c++20/asan=on/ubsan=off-3 ] 🚀  Start image=catthehacker/ubuntu:act-latest
[build/buster/g++/c++17/asan=off/ubsan=off-1  ]   🐳  docker pull image=catthehacker/ubuntu:act-latest platform= username= forcePull=true
[build/jammy/g++/c++20/asan=on/ubsan=off-4    ]   🐳  docker pull image=catthehacker/ubuntu:act-latest platform= username= forcePull=true
[build/focal/clang++/c++17/asan=off/ubsan=on-2]   🐳  docker pull image=catthehacker/ubuntu:act-latest platform= username= forcePull=true
[build/focal/g++-10/c++20/asan=on/ubsan=off-3 ]   🐳  docker pull image=catthehacker/ubuntu:act-latest platform= username= forcePull=true
[build/buster/g++/c++17/asan=off/ubsan=off-1  ]   🐳  docker create image=catthehacker/ubuntu:act-latest platform= entrypoint=["tail" "-f" "/dev/null"] cmd=[]
[build/buster/g++/c++17/asan=off/ubsan=off-1  ]   🐳  docker run image=catthehacker/ubuntu:act-latest platform= entrypoint=["tail" "-f" "/dev/null"] cmd=[]
