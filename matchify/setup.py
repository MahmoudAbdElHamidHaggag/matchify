from setuptools import setup, find_packages

setup(
    name='matchify',
    version='1.0.0',
    description='A Frappe app to handle matching functionality between entities.',
    author='Mahmoud Abd El Hamid Haggag',
    author_email='haggag.haggag224@gmail.com',
    packages=find_packages(),
    include_package_data=True,
    install_requires=['frappe'],
    zip_safe=False
)
