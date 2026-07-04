Import('env')

builder = env.builder()

# build library from lib sources - not added to environment
lib = env.build_lib(Glob('src/*.cpp'), name = env.module_format_name())

# build test binary, linking with the library built above and test libs
test = env.build_test(Glob('test/*.cpp'), libs = [env.module_format_name()])

# build binaries and add them to environment, linking with the library built above
import os
for src in Glob('bin/*.cpp'):
    bin_name = os.path.basename(os.path.splitext(str(src))[0])
    env.build_bin(src, name = bin_name, libs = [env.module_format_name()])