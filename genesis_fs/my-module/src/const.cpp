#include <fmt/format.h>

#include <my-project/my-module/const.hpp>

namespace my_project::my_module
{

void my_module_func()
{
    fmt::print("Hello from my_module_func! The const is: {}\n", my_module_const);
}

} // namespace my_project::my_module