import shutil

def get_disk_usage():
    # Get disk usage statistics about the root partition
    total, used, free = shutil.disk_usage("/")

    print(f"Disk Usage Report:")
    print(f"------------------")
    print(f"Total: {total // (2**30)} GiB")
    print(f"Used: {used // (2**30)} GiB")
    print(f"Free: {free // (2**30)} GiB")
    print(f"Percentage Used: {(used / total) * 100:.2f}%")

if __name__ == "__main__":
    get_disk_usage()
