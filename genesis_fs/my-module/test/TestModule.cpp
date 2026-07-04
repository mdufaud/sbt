#include <gtest/gtest.h>

#include <my-project/my-module/const.hpp>

namespace test
{

class TestModule: public ::testing::Test
{
    protected:
        TestModule() = default;
        virtual ~TestModule() = default;
        virtual void SetUp() {}
        virtual void TearDown() {}
};

TEST_F(TestModule, test_const)
{
    ASSERT_EQ(my_project::my_module::my_module_const, 42);
}

} // namespace test
