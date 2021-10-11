#!/bin/bash

# This shell script will import the last theme version from
# https://github.com/betagouv/itou-theme

echo "Running the Upload Itou theme"

cd $APP_HOME

# Folder where the theme will be temporary stocked
tmpFolder="$APP_DIR/tmp"
tmpFolderDistribSources="$tmpFolder/dist"

# local folder where the source will be updated
localFolderTheme="$APP_DIR/itou/static/vendor/theme-inclusion"

repository="https://github.com/betagouv/itou-theme"

# create temporary folder
mkdir -p $tmpFolder

copy_and_replace_folder_theme() {
    local folderToReplace=$1
    cp -TRv "$tmpFolderDistribSources/$folderToReplace/" "$localFolderTheme/$folderToReplace/"
}

# clone the repository in temp folder
git clone $repository $tmpFolder

# copy and replace all files in those folders
copy_and_replace_folder_theme fonts
copy_and_replace_folder_theme images
copy_and_replace_folder_theme javascripts
copy_and_replace_folder_theme stylesheets

rm -rf $tmpFolder
