def do_stuff():
    # We use 'os' as a local variable, shadowing the built-in
    os = "Operating System"
    api_key = "shadowed_secret_key"  # SEC002
    print(f"{os} key is {api_key}")
